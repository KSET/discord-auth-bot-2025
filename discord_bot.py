import os
import discord
import aiohttp
import asyncio
import datetime
import json
import uuid
import psycopg2
from psycopg2 import pool, sql
from discord.ext import commands, tasks
from discord import app_commands
from discord.utils import get
from dotenv import load_dotenv



# load_dotenv(dotenv_path='./.env')
# load_dotenv(dotenv_path='./.env.db')

# .env varijable za bot
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SERVER_ID = discord.Object(id=int(os.getenv("SERVER_ID")))

# .env varijable za bazu podataka
DB_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_DB = os.getenv("POSTGRES_DB")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_PASSWORD=os.getenv("POSTGRES_PASSWORD")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='/', intents=intents)

# Globalna varijabla za PostgreSQL connection pool
db_pool = None

def init_db():
    global db_pool
    try:
        db_pool = psycopg2.pool.SimpleConnectionPool(1, 20,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        print("spojeno sa bazom")       
        
        with db_pool.getconn() as conn:
            with conn.cursor() as cur:
                # Tablica za pohranu verificiranih korisnika
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        "discordId" TEXT UNIQUE NOT NULL,
                        priv_email TEXT
                    );
                """)
            conn.commit()
            db_pool.putconn(conn)
        
    except psycopg2.OperationalError as e:
        print("Ne spaja se s bazom zbog : ",e)
        db_pool = None

def insert_user_to_db(discord_id: str, private_email: str):

    if db_pool is None:
        return False
    
    conn = None
    try:
        conn = db_pool.getconn()
        with conn.cursor() as cur:
            insert_query = """
                INSERT INTO users ("discordId", priv_email)
                VALUES (%s, %s)
                ON CONFLICT ("discordId") DO UPDATE SET priv_email = EXCLUDED.priv_email
                RETURNING id;
            """
            cur.execute(insert_query, (discord_id, private_email))
            new_user_id = cur.fetchone()[0]
            print(f"Umetnut korisnik {new_user_id}")
            conn.commit()
            return True
    except psycopg2.Error as e:
        print(f"Greska pri umetanju : {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            db_pool.putconn(conn)

def get_all_verified_users_from_db():
    if db_pool is None:
        return []
        
    conn = None
    try:
        conn = db_pool.getconn()
        with conn.cursor() as cur:
            query = "SELECT \"discordId\", priv_email FROM users WHERE priv_email IS NOT NULL;"
            cur.execute(query)
            users = [{"discordId": row[0], "priv_email": row[1]} for row in cur.fetchall()]
            return users
    except psycopg2.Error as e:
        print(f"[DB ERROR] Greška pri dohvaćanju korisnika: {e}")
        return []
    finally:
        if conn:
            db_pool.putconn(conn)

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

async def wait_for_verification(state: str, timeout: int = 300):
    start_time = datetime.datetime.now().timestamp()
    while datetime.datetime.now().timestamp() - start_time < timeout:
        try:
            async with aiohttp.ClientSession() as session:
                print(f"LOGIRANJE: {state} ({datetime.datetime.now().timestamp() - start_time:.2f}")
                async with session.get(f"http://verifikator:8000/oauth/status?state={state}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"BACKEND STATUS: {data.get('status')} od backenda.")
                        if data.get("status") == "success":
                            return data.get("private_email")
                        elif data.get("status") == "fail":
                            print(f"krivi status: {data.get('reason')}")
                            return None
                    elif resp.status == 404:
                        print(f"NEMA OAUTH, SERVER OD GOOGLA ILI KONEKCIJA.")
                        return None
                    else:
                        pass
        except aiohttp.ClientConnectorError:
            pass
        except Exception as e:
            print(f"Greška pri provjeri status : {e}")

        await asyncio.sleep(2)

    print(f"Verifikacija istekla nakon {timeout} sekundi.")
    return None

# Mapa uloga za status članstva
status_clanstva_role = {
    "plava": "Plavi",
    "narančasta": "Narančasti",
    "crvena": "Crveni",
}

section_roles_map_test = {
    "comp": "Comp",
    "tech": "Tech",
    "pi": "Pi",
    "glazbena": "Glazbena",
    "foto": "Foto",
    "video": "Video",
    "bike": "Bike",
    "dramska": "Dramsksa",
    "disco": "Disco",
}


def get_roles_map(guild: discord.Guild, roles_dict: dict):
    roles_map = {}
    for status, role_name in roles_dict.items():
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            roles_map[status] = role
    return roles_map

async def update_member_role(member: discord.Member, new_status: str, roles_map: dict):
    roles_to_remove = []
    
    for status, role in roles_map.items():
        if role in member.roles and status != new_status:
            roles_to_remove.append(role)
    
    if roles_to_remove:
        try:
            await member.remove_roles(*roles_to_remove, reason="Status update")
            print(f"Uklonjene uloge: {', '.join([r.name for r in roles_to_remove])} za {member.display_name}")
        except discord.Forbidden:
            print(f"NEMA PRAVA ZA ULOGE PONOVNO INVITAJ ILI PROVJERI DODANI ROLE, NEKAD JE TAMO PROBLEM {member.display_name}.")

    role_to_add = roles_map.get(new_status)
    if role_to_add and role_to_add not in member.roles:
        try:
            await member.add_roles(role_to_add, reason="Dodan status")
            print(f"Dodana uloga: {role_to_add.name} za {member.display_name}")
        except discord.Forbidden:
            print(f"Bot nema dozvolu za dodjeljivanje uloge {role_to_add.name} korisniku {member.display_name}.")
        except Exception as e:
            print(f"Greška pri dodjeljivanju uloge: {e}")

async def update_member_section_role(member: discord.Member, new_section: str, roles_map: dict):
    roles_to_add = []
    roles_to_remove = []
    
    new_role = roles_map.get(new_section)
    
    # Ukloni sve stare sekcijske uloge ako dode do promjene
    all_section_roles = roles_map.values()
    for role in all_section_roles:
        if role in member.roles and role != new_role:
            roles_to_remove.append(role)
    
    # Dodaj novu ulogu ako je pronađena i nije dana
    if new_role and new_role not in member.roles:
        roles_to_add.append(new_role)

    if roles_to_remove:
        try:
            await member.remove_roles(*roles_to_remove, reason="Promjena sekcije")
            print(f"Uklonjene sekcijske uloge: {', '.join([r.name for r in roles_to_remove])} za {member.display_name}")
        except discord.Forbidden:
            print(f"OPET ULOGA {member.display_name}.")
    
    if roles_to_add:
        try:
            await member.add_roles(*roles_to_add, reason="Dodijeljena sekcija")
            print(f"Dodana sekcijska uloga: {new_role.name} za {member.display_name}")
        except discord.Forbidden:
            print(f"Bot nema dozvolu za dodjeljivanje uloge {new_role.name} korisniku {member.display_name}.")
        except Exception as e:
            print(f"Greška pri dodjeljivanju uloge: {e}")


#@tasks.loop(seconds=15)
@tasks.loop(time=datetime.time(hour=3))
async def daily_status_check():
    await bot.wait_until_ready()
    print(f"PROVJERA U TRENUTKU ({datetime.datetime.now().strftime('%H:%M:%S')})")
    
    guild = bot.get_guild(SERVER_ID.id)
    if not guild:
        print(f"NEMA SERVERA SA TIM SERVERID") 
        return

    # Dohvaćanje korisnika i e-mailova iz baze (pokrenuto u executoru)
    all_verified_users = await bot.loop.run_in_executor(None, get_all_verified_users_from_db)
    
    if not all_verified_users:
        print("Server nema korisnika pa skipa.")
        return
        
    status_roles_map = get_roles_map(guild, status_clanstva_role)
    section_roles_map = get_roles_map(guild, section_roles_map_test)
    emails_to_check = []
    users_to_update = {}

    #special role za crvene
    crveni_role = discord.utils.get(guild.roles, name="Crveni")
    for user_data in all_verified_users:
        member = guild.get_member(int(user_data["discordId"]))
        
        if member and crveni_role and crveni_role in member.roles:
            continue
        
        if member and user_data["priv_email"]:
            emails_to_check.append(user_data["priv_email"])
            users_to_update[user_data["priv_email"]] = member

    if not emails_to_check:
        return

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "http://verifikator:8000/verify-emails",
                json={"emails": emails_to_check},
                timeout=10
            ) as resp:
                if resp.status == 200:
                    all_members_data = await resp.json()
                    
                    for email, server_data in all_members_data.items():
                        member = users_to_update.get(email)
                        if member:
                            new_status = server_data.get("status_clanstva", "").lower()
                            new_section = server_data.get("section", "").lower()

                            await update_member_role(member, new_status, status_roles_map)
                            
                            await update_member_section_role(member, new_section, section_roles_map)
                else:
                    print(f"ERROR {resp.status}. Preskačem provjeru uloga.")
        except Exception as e:
            print(f"daily_status_check error : {e}")
    
    print(f"Dnevna provjera člansttva zavrsena u ({datetime.datetime.now().strftime('%H:%M:%S')})")

class RegisterView(discord.ui.View):
    def __init__(self, oauth_url: str, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.add_item(discord.ui.Button(label="Verificiraj se", url=oauth_url, style=discord.ButtonStyle.link))

@bot.tree.command(name="register", description="Verificiraj se putem OAutha.", guild=SERVER_ID)
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
    
    await interaction.response.defer(ephemeral=True)

    try:
        state = str(uuid.uuid4())
        discord_user_id = str(interaction.user.id)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://verifikator:8000/generate-oauth-link",
                json={
                    "state": state,
                    "izvor": "Discord"
                },
                headers={"Content-Type": "application/json"}
            ) as oauth_resp:
                if oauth_resp.status != 200:
                    error_text = await oauth_resp.text()
                    await interaction.followup.send(
                        f"Problem sa generacijom OAUTH-a, pokušajte ponovno kasnije ili kontaktirajte administraciju: {error_text}",
                        ephemeral=True
                    )
                    return

                oauth_data = await oauth_resp.json()
                oauth_url = oauth_data.get("oauth_url")

                if not oauth_url:
                    await interaction.followup.send(
                        "Nismo mogli generirati OAuth link.",
                        ephemeral=True
                    )
                    return

        verification_message = await interaction.followup.send(
            "Kliknite na gumb ispod kako biste započeli proces verifikacije.",
            view=RegisterView(oauth_url, timeout=300),
            ephemeral=True
        )
    
        verified_email = await wait_for_verification(state, timeout=300)
    
        try:
            await verification_message.delete()
        except discord.NotFound:
            pass 
    
        if verified_email:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://verifikator:8000/verify-email",
                    json={"email": verified_email},
                    headers={"Content-Type": "application/json"}
                ) as status_resp:
                    if status_resp.status == 200:
                        status_data = await status_resp.json()
                        status = status_data.get("status_clanstva", "").lower()
                        full_name = status_data.get("full_name", "N/A")
                        sekcija = status_data.get("section", "").lower()
                        
                        guild = interaction.guild
                        
                        status_roles_map = get_roles_map(guild, status_clanstva_role)
                        if status_roles_map:
                            await update_member_role(member, status, status_roles_map)

                        section_roles_map = get_roles_map(guild, section_roles_map_test)
                        if section_roles_map:
                            await update_member_section_role(member, sekcija, section_roles_map)
                            
                        success_msg = await interaction.followup.send(
                            f"Dobrodošli, **{full_name}**! Vaš status članstva je **{status}** i u sekciji ste **{sekcija}**.",
                            ephemeral=True,
                        )
                        asyncio.create_task(delete_later(success_msg, delay=35))

                        await bot.loop.run_in_executor(None, insert_user_to_db, discord_user_id, verified_email)
                    else:
                        await interaction.followup.send(
                            "Došlo je do greške pri dohvaćanju vašeg statusa nakon verifikacije. Kontaktirajte administratora na comp@kset.org.",
                            ephemeral=True, delay=60
                        )
        else:
            await interaction.followup.send(
                "Isteklo je vrijeme za verifikaciju (5 minuta). Molimo pokušajte ponovo.",
                ephemeral=True
            )

    except aiohttp.ClientConnectorError:
        await interaction.followup.send(
            "Problem s povezivanjem na verifikacijski servis. Molimo pokušajte ponovo kasnije ili kontaktirajte comp@kset.org.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"Došlo je do neočekivane greške s naše strane, pokušajte ponovno i obratite se na comp@kset.org: {e}",
            ephemeral=True
        )

@bot.tree.command(name="check_status", description="Ručno provjerava i ažurira status članstva za sve verificirane korisnike.", guild=SERVER_ID)
@app_commands.checks.has_role("Savjetnik")
async def check_status_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    print(f"Komanda /check_status pokrenuta od strane {interaction.user.display_name}")

    async with aiohttp.ClientSession() as session:
        async with session.post("http://verifikator:8000/refresh-cache") as resp:
            if resp.status == 200:
                refresh_result = await resp.json()
                print("Uspješno osvježen cache")
            else:
                text = await resp.text()
                await interaction.followup.send(f"Greška pri osvježavanju cachea: {text}", ephemeral=True)
                return  

    try:
        await daily_status_check() 
        await interaction.followup.send(
            "Provjera statusa članstva i osvježavanje cachea je završeno.", ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"Došlo je do greške pri provjeri statusa: {e}", ephemeral=True
        )

@bot.event
async def on_ready():
    print(f"Bot prijavljen kao {bot.user} (ID: {bot.user.id})")
    try:
        init_db()
        
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
    elif None in [DB_HOST, POSTGRES_USER, POSTGRES_DB]:
        print("Greška: Neke varijable za bazu podataka nisu postavljene u .env datoteci.")
    else:
        bot.run(DISCORD_BOT_TOKEN)