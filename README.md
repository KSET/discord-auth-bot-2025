# Discord Bot za Upravljanje Članstvom
Ovaj Discord bot je dizajniran za automatizaciju verifikacije korisnika i upravljanja ulogama na vašem serveru na temelju statusa članstva i sekcijske pripadnosti. Integrira se s vanjskom OAuth uslugom i PostgreSQL bazom podataka kako bi uloge korisnika bile sinkronizirane.

Značajke
Verifikacija korisnika putem OAutha: Članovi mogu koristiti slash naredbu /register za pokretanje OAuth procesa, povezujući svoj Discord račun s verificiranom e-mail adresom.

Automatsko dodjeljivanje uloga: Automatski dodjeljuje Discord uloge (npr. "Plavi", "Narančasti", "Crveni") na temelju verificiranog statusa članstva korisnika preuzetog iz vanjske usluge.

Upravljanje sekcijskim ulogama: Dodjeljuje specifične sekcijske uloge (npr. "Comp", "Tech", "Glazbena", "Foto" itd.) korisnicima na temelju njihove verificirane sekcijske pripadnosti.

Dnevne provjere statusa članstva: Planirani zadatak se pokreće svakodnevno kako bi ponovno verificirao status članstva svih registriranih korisnika u odnosu na vanjsku uslugu i ažurira njihove uloge ako se otkriju bilo kakve promjene. Korisnici s ulogom "Crveni" automatski se preskaču iz ovih provjera.

Integracija s PostgreSQL bazom podataka: Sigurno pohranjuje verificirane Discord ID-ove korisnika i njihove pridružene privatne e-mail adrese za održavanje trajnih podataka.

Početak rada
Slijedite ove korake za pokretanje vašeg Discord bota za članstvo.

Preduvjeti
Prije nego što počnete, provjerite imate li instalirano i postavljeno sljedeće:

Python 3.8+: Preuzmite s python.org.

PostgreSQL poslužitelj baze podataka: Provjerite je li PostgreSQL instanca pokrenuta i dostupna.

Discord Bot aplikacija i token:

Idite na Discord Developer Portal.

Stvorite novu aplikaciju.

Pod "Bot" dodajte bota i kopirajte njegov token.

Omogućite PRESENCE INTENT i MESSAGE CONTENT INTENT pod odjeljkom "Privileged Gateway Intents".

ID Discord poslužitelja: Možete ga dobiti omogućavanjem Developer Modea u Discord postavkama, desnim klikom na vaš poslužitelj i odabirom "Copy ID".

Vanjska pozadinska usluga (Backend): Ovaj bot se oslanja na vanjsku uslugu (u kodu nazvanu "backend") koja radi na http://localhost:8000. Ova usluga je ključna za:

Generiranje OAuth veza.

Rukovanje OAuth povratnim pozivom.

Pružanje statusa članstva korisnika i informacija o sekciji na temelju njihove e-mail adrese.

Bot neće ispravno funkcionirati bez pokrenute pozadinske usluge.

Instalacija
Klonirajte repozitorij (ako je vaš kod u Git repozitoriju):

git clone <url-vašeg-repozitorija>
cd <vaš-projektni-direktorij>

Ako ne, navigirajte do direktorija gdje se nalaze Python datoteke vašeg bota.

Stvorite Python virtualno okruženje (preporučeno):

python -m venv venv

Aktivirajte virtualno okruženje:

Windows:

.\venv\Scripts\activate

macOS/Linux:

source venv/bin/activate

Instalirajte ovisnosti:
Stvorite datoteku requirements.txt u korijenskom direktoriju vašeg projekta sa sljedećim sadržajem:

discord.py
aiohttp
psycopg2-binary
python-dotenv

Zatim ih instalirajte:

pip install -r requirements.txt

Konfiguracija
Stvorite datoteku pod nazivom .env u korijenskom direktoriju vašeg projekta i popunite je sljedećim varijablama okoline:

DISCORD_BOT_TOKEN="VAŠ_DISCORD_BOT_TOKEN_OVDJE"
SERVER_ID="VAŠ_DISCORD_SERVER_ID_OVDJE"

DB_NAME="ime_vaše_baze_podataka"
DB_USER="korisnik_vaše_baze_podataka"
DB_PASSWORD="lozinka_vaše_baze_podataka"
DB_HOST="localhost" # Ili vaš PostgreSQL host
DB_PORT="5432"      # Ili vaš PostgreSQL port

Zamijenite "VAŠ_DISCORD_BOT_TOKEN_OVDJE" tokenom koji ste kopirali s Discord Developer Portala.

Zamijenite "VAŠ_DISCORD_SERVER_ID_OVDJE" ID-om vašeg Discord poslužitelja.

Prilagodite DB_NAME, DB_USER, DB_PASSWORD, DB_HOST i DB_PORT kako bi odgovarali konfiguraciji vaše PostgreSQL baze podataka.

Postavljanje baze podataka
Bot automatski pokušava stvoriti tablicu users pri pokretanju ako ona ne postoji. Provjerite ima li vaš PostgreSQL korisnik potrebne dozvole za stvaranje tablica u navedenoj bazi podataka.

Struktura tablice je:

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    "discordId" TEXT UNIQUE NOT NULL,
    priv_email TEXT
);

Pokretanje bota
Nakon što su svi preduvjeti i konfiguracije postavljeni, možete pokrenuti bota:

python ime_vaše_bot_datoteke.py

(Zamijenite ime_vaše_bot_datoteke.py stvarnim nazivom vaše Python datoteke, npr. main.py ili bot.py).

Upotreba
Pozovite bota: Pozovite svog bota na Discord poslužitelj pomoću OAuth2 URL-a generiranog na Discord Developer Portalu (pod "OAuth2" -> "URL Generator"). Provjerite jeste li mu dodijelili dozvole Manage Roles i Send Messages.

Pokrenite naredbu za registraciju: U bilo kojem kanalu gdje bot ima dozvole, članovi mogu upisati:

/register

Bot će odgovoriti jedinstvenom OAuth vezom.

Dovršite verifikaciju: Član klikne na priloženu vezu i dovrši OAuth proces putem vaše vanjske pozadinske usluge.

Dodjela uloga: Nakon uspješne verifikacije, bot će korisniku dodijeliti odgovarajući status članstva i sekcijske uloge.

Dnevne provjere: Bot će automatski obavljati dnevne provjere (prema zadanim postavkama u 2:06 ujutro, ili odmah pri pokretanju ako je konfigurirano) kako bi osigurao da su uloge ažurne.

Rješavanje problema
Bot se ne pokreće:

Provjerite svoju .env datoteku za nedostajuće ili netočne varijable (posebno DISCORD_BOT_TOKEN, SERVER_ID i vjerodajnice baze podataka).

Provjerite je li vaša PostgreSQL baza podataka pokrenuta i dostupna s mjesta gdje se bot pokreće.

Provjerite izlaz konzole za sve poruke psycopg2.OperationalError.

Slash naredbe se ne sinkroniziraju:

Provjerite je li SERVER_ID u vašoj .env datoteci točan.

Provjerite je li botu omogućen opseg applications.commands u njegovom URL-u za poziv.

Pričekajte nekoliko minuta nakon pokretanja bota; ponekad sinkronizacija naredbi može potrajati.

Problemi s dodjelom uloga:

Provjerite je li uloga bota na vašem Discord poslužitelju iznad uloga koje treba dodijeliti (npr. "Plavi", "Crveni", "Comp", "Tech"). Discordova hijerarhija dozvola to diktira.

Provjerite ima li bot dozvolu Manage Roles.

Provjerite pravopis naziva uloga u vašim rječnicima status_clanstva_role i section_roles_map_test u odnosu na stvarne nazive uloga u Discordu.

OAuth/Verifikacija neuspješna:

Najčešći uzrok je vanjska pozadinska usluga koja nije pokrenuta ili je nedostupna na http://localhost:8000. Provjerite je li ova usluga operativna i ispravno konfigurirana.

Provjerite izlaz konzole bota za aiohttp.ClientConnectorError ili druge povezane pogreške.

Kontakt
Ako naiđete na trajne probleme ili imate pitanja, obratite se administratorima na comp@kset.org.
