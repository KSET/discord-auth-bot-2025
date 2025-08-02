import os
import discord
import aiohttp
import asyncio
import datetime
import json
from discord.ext import commands, tasks
from discord import app_commands
from discord.utils import get
from dotenv import load_dotenv

load_dotenv()
CACHE_FILE = os.getenv("USERS_PATH_DISCORD")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SERVER_ID = discord.Object(id=int(os.getenv("SERVER_ID")))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='/', intents=intents)
verified_users = {}

def load_verified_users():
    global verified_users
    print("Ulaz u load_verified_users")
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            try:
                verified_users = json.load(f)
                print(f"Učitano {len(verified_users)} verificiranih korisnika.")
            except json.JSONDecodeError:
                print(f"Inicijaliziram prazan cache jer nemogu pristupiti {CACHE_FILE}.")
                verified_users = {}
    else:
        verified_users = {}
        print("Cache datoteka ne postoji.")

def save_verified_users():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(verified_users, f, indent=1, ensure_ascii=False)
    print("Verificirani korisnici spremljeni u cache.")

async def delete_later(message: discord.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
        print(f"Poruka obrisana nakon {delay} sekundi.")
    except discord.NotFound:
        print("Poruka je već obrisana ili nije pronađena.")
    except discord.Forbidden:
        print("Bot nema dozvolu za brisanje poruke.")
    except discord.HTTPException as e:
        print(f"Greška pri brisanju poruke: {e}")

class SimpleInputModal(discord.ui.Modal, title="Verifikacija članstva"):
    email = discord.ui.TextInput(
        label="Upiši svoj email iz forme",
        placeholder="ime.prezime@kset.org",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        email = self.email.value.strip()
        await interaction.response.defer(ephemeral=True)

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    "http://localhost:8000/verify-email",
                    json={"email": email},
                    headers={"Content-Type": "application/json"}
                ) as verify_resp:
                    if verify_resp.status != 200:
                        msg = await interaction.followup.send(
                            "Vaša adresa nije pronađena. Ako mislite da je greška, kontaktirajte administratora.",
                            ephemeral=True
                        )
                        asyncio.create_task(delete_later(msg, delay=60))
                        return

                async with session.post(
                    "http://localhost:8000/generate-oauth-link",
                    json={"email": email},
                    headers={"Content-Type": "application/json"}
                ) as oauth_resp:
                    if oauth_resp.status != 200:
                        error_text = await oauth_resp.text()
                        msg = await interaction.followup.send(
                            f"Problem sa generacijom OATH-a, pokusajte ponovno kasnije ili kontaktirajte administraciju: {error_text}",
                            ephemeral=True
                        )
                        asyncio.create_task(delete_later(msg, delay=60))
                        return

                    oauth_data = await oauth_resp.json()
                    oauth_url = oauth_data.get("oauth_url")
                    state = oauth_data.get("state")

                    if not oauth_url or not state:
                        msg = await interaction.followup.send(
                            "Nismo mogli generirati OAuth link ili state.",
                            ephemeral=True
                        )
                        asyncio.create_task(delete_later(msg, delay=60))
                        return

                    msg = await interaction.followup.send(
                        f"Verificiraj se putem ovog linka: {oauth_url}\n\n"
                        "Čekamo potvrdu prijave (imate 60 sekundi)...",
                        ephemeral=True
                    )

                verified_email = await wait_for_verification(state, timeout=60)

                if verified_email:
                    async with session.post(
                        "http://localhost:8000/verify-email",
                        json={"email": verified_email},
                        headers={"Content-Type": "application/json"}
                    ) as status_resp:
                        if status_resp.status == 200:
                            status_data = await status_resp.json()
                            status = status_data.get("status_clanstva", "").lower()
                            full_name = status_data.get("full_name", "N/A")
                            private_email = status_data.get("private_email", email)

                            guild = interaction.guild
                            member = interaction.user
                            
                            roles_map = get_roles_map(guild)
                            if roles_map:
                                await update_member_role(member, status, roles_map)
                                
                            success_msg = await interaction.followup.send(
                                f"Dobrodošli, **{full_name}**! Vaš status članstva je **{status}**.",
                                ephemeral=True,
                            )
                            asyncio.create_task(delete_later(success_msg, delay=35))

                            user_id = str(interaction.user.id)
                            if user_id and private_email:
                                verified_users[user_id] = {
                                    "private_email": private_email,
                                    "status": status
                                }
                                save_verified_users()
                        else:
                            msg = await interaction.followup.send(
                                "Došlo je do greške pri dohvaćanju vašeg statusa nakon verifikacije. Kontaktirajte administratora na comp@kset.org.",
                                ephemeral=True
                            )
                            asyncio.create_task(delete_later(msg, delay=60))
                else:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    msg = await interaction.followup.send(
                        "Isteklo je vrijeme za verifikaciju (60 sekundi). Molimo pokušajte ponovo.",
                        ephemeral=True
                    )
                    asyncio.create_task(delete_later(msg, delay=30))

            except aiohttp.ClientConnectorError:
                msg = await interaction.followup.send(
                    "Problem s povezivanjem na verifikacijski servis. Molimo pokušajte ponovo kasnije ili kontaktirajte comp@kset.org.",
                    ephemeral=True
                )
                asyncio.create_task(delete_later(msg, delay=60))
            except Exception as e:
                msg = await interaction.followup.send(
                    f"Došlo je do neočekivane greške s naše strane, pokušajte ponovno i obratite se na comp@kset.org: {e}",
                    ephemeral=True
                )
                asyncio.create_task(delete_later(msg, delay=60))

# Unutar funkcije wait_for_verification
async def wait_for_verification(state: str, timeout: int = 60):
    start_time = datetime.datetime.now().timestamp()
    while datetime.datetime.now().timestamp() - start_time < timeout:
        try:
            async with aiohttp.ClientSession() as session:
                print(f"[BOT-LOG] Provjeravam status za state: {state} ({datetime.datetime.now().timestamp() - start_time:.2f}s elapsed)")
                async with session.get(f"http://localhost:8000/oauth/status?state={state}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"[BOT-LOG] Primljen status: {data.get('status')} od backenda.")
                        if data.get("status") == "success":
                            return data.get("private_email")
                        elif data.get("status") == "fail":
                            print(f"[BOT-LOG] Backend javlja da je status krivi: {data.get('reason')}")
                            return None
                    elif resp.status == 404:
                        print(f"[BOT-LOG] STATUS oautha nije aktivan, pokusaj ponovno.")
                        return None
                    else:
                        print("idk")
        except aiohttp.ClientConnectorError:
            print(f"[BOT-LOG] Greška povezivanja na backend. Pokusavam opet")
        except Exception as e:
            print(f"[BOT-LOG] Greška pri provjeri statusa: {e}")

        await asyncio.sleep(2)

    print(f"[BOT-LOG] Verifikacija istekla nakon {timeout} sekundi.")
    return None

status_clanstva_role = {
    "plava": "Plavi",
    "narancasta": "Narančasti",
    "crvena": "Crveni",
}

def get_roles_map(guild: discord.Guild):
    roles_map = {}
    for status, role_name in status_clanstva_role.items():
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            roles_map[status] = role
    return roles_map

async def update_member_role(member: discord.Member, new_status: str, roles_map: dict):
    roles_to_remove = []
    
    # Ukloni role koji ima da nema narancastu i plavu
    for status, role in roles_map.items():
        if role in member.roles and status != new_status:
            roles_to_remove.append(role)
    
    if roles_to_remove:
        try:
            await member.remove_roles(*roles_to_remove, reason="Status update")
            print(f"[INFO] Uklonjene uloge: {', '.join([r.name for r in roles_to_remove])} za {member.display_name}")
        except discord.Forbidden:
            print(f"[ERROR] Bot nema dozvolu za uklanjanje uloga za {member.display_name}.")

    role_to_add = roles_map.get(new_status)
    if role_to_add and role_to_add not in member.roles:
        try:
            await member.add_roles(role_to_add, reason="Dodan status")
            print(f"[INFO] Dodana uloga: {role_to_add.name} za {member.display_name}")
        except discord.Forbidden:
            print(f"[ERROR] Bot nema dozvolu za dodjeljivanje uloge {role_to_add.name} korisniku {member.display_name}.")
        except Exception as e:
            print(f"[ERROR] Greška pri dodjeljivanju uloge: {e}")

#@tasks.loop(time=datetime.time(hour=3, minute=0)) # Vrti se u 3 ujutro svaki dan
@tasks.loop(seconds=15) # Koristite ovo za testiranje
async def daily_status_check():
    await bot.wait_until_ready()
    print(f"PROVJERA U TRENUTKU ({datetime.datetime.now().strftime('%H:%M:%S')})")
    
    guild = bot.get_guild(SERVER_ID.id)
    if not guild:
        print(f"NEMA SERVERA SA TIM SERVERid")
        return

    # Učitaj cache na početku provjere
    load_verified_users()
    roles_map = get_roles_map(guild)

    async with aiohttp.ClientSession() as session:
        cache_modified = False
        
        user_ids_to_check = list(verified_users.keys())
        for user_id in user_ids_to_check:
            user_data = verified_users.get(user_id)
            if not user_data:
                continue

            member = guild.get_member(int(user_id))
            if not member:
                print(f"Korisnika nema, micem iz cashea")
                del verified_users[user_id]
                cache_modified = True
                continue

            private_email = user_data.get("private_email")

            try:
                async with session.post(
                    "http://localhost:8000/verify-email",
                    json={"email": private_email},
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        server_data = await resp.json()
                        new_status = server_data.get("status_clanstva", "").lower()
                        
                        if not new_status:
                            print(f"[WARN] Nije pronađen status članstva za {member.display_name} s emailom {private_email}.")
                            continue

                        # 2. Ažuriranje uloga na Discordu na temelju statusa sa servera
                        await update_member_role(member, new_status, roles_map)
                        
                        # 3. Ažuriranje cachea kako bi odgovarao statusu sa servera
                        old_status_in_cache = user_data.get("status")
                        if old_status_in_cache != new_status:
                            user_data["status"] = new_status
                            cache_modified = True
                            print(f"[INFO] Ažuriran status u cacheu za {member.display_name}: {old_status_in_cache} → {new_status}")
                            
                    else:
                        print(f"[ERROR] Backend vratio {resp.status} za {member.display_name}. Preskačem provjeru uloga.")

            except Exception as e:
                print(f"[ERROR] Neočekivana greška za {member.display_name}: {e}")

        # spremi cache ako se nesto novo dogodilo

        if cache_modified:
            save_verified_users()
            print("[INFO] Verificirani korisnici cache spremljen u json")
    
    print(f"[INFO] Daily membership status check completed. ({datetime.datetime.now().strftime('%H:%M:%S')})")

# --- Discord komande ---
@bot.tree.command(name="register", description="Verificiraj se putem emaila", guild=SERVER_ID)
async def register(interaction: discord.Interaction):
    forbidden_roles_names = {"Plavi", "Crveni", "Narančasti"}
    member = interaction.user

    guild = interaction.guild
    if not isinstance(member, discord.Member):
        member = guild.get_member(member.id)
    
    if member is None:
        await interaction.response.send_message(
            "Ne mogu dohvatiti tvoje podatke o korisniku na serveru. Pokušajte ponovo.", ephemeral=True
        )
        return

    user_role_names = {role.name for role in member.roles}
    if forbidden_roles_names.intersection(user_role_names):
        await interaction.response.send_message(
            "Već ti je dodijeljen status članstva. Ako misliš da je greška, kontaktiraj admine.", ephemeral=True
        )
        return

    await interaction.response.send_modal(SimpleInputModal())

# --- Bot Events ---
@bot.event
async def on_ready():
    print(f"Bot prijavljen kao {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync(guild=SERVER_ID)
        print(f"Sinkronizirane {len(synced)} komande na serveru {SERVER_ID.id}.")
        
        if not daily_status_check.is_running():
            daily_status_check.start()
            print("Pokrenut daily_status_check.")
        else:
            print("daily_status_check već radi.")
    except Exception as e:
        print(f"Greška pri pokretanju bota ili sinkronizaciji komandi: {e}")

if __name__ == "__main__":
    if DISCORD_BOT_TOKEN is None:
        print("Greška: DISCORD_BOT_TOKEN nije postavljen u .env datoteci.")
    elif SERVER_ID.id is None:
        print("Greška: SERVER_ID nije postavljen u .env datoteci.")
    else:
        bot.run(DISCORD_BOT_TOKEN)
