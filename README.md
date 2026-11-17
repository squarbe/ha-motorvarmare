# Motorvärmare

Egen Home Assistant-integration för motorvärmare: avresor, temperaturberoende uppvärmningstid och säker styrning av Shelly-reläer. Version 0.7.0, betatest.

Ersätter beta 0.1.0, som aldrig installerades. Den här versionen är **en** integration. Varje motorvärmaruttag läggs till som en underpost.

**Nytt i 0.7.0:** lugnare beräkning. Uppvärmningstiden har hysteres på 0,5 °C, och en starttid som ligger mer än 4 timmar fram är preliminär och uppdateras högst var 15:e minut. Det ger färre uppdateringar i historiken. Kalendrar läses först när HA har startat helt, och de omförsöks tyst under uppstarten. Se avsnitt 6 och 7.

**Nytt i 0.6.0:** larmmottagare per uttag. Larmet för ett uttag kan gå till en eller flera egna telefoner, t.ex. den som kör bilen. Uttag utan egna mottagare använder integrationens gemensamma.

**Nytt i 0.5.0:** kortet visar alla uttag automatiskt när `entity` utelämnas, så ett nytt uttag dyker upp i dashboarden utan ändringar. Kortet har en visuell redigerare och visar effekt från reläet. Se avsnitt 3.

**Nytt i 0.4.1:** egen ikon för integrationen (mappen `brand/`, kräver HA 2026.3 eller senare). Ikonen bygger på symbolen `car-electric` från Material Design Icons (Apache 2.0).

**Nytt i 0.4.0:** du väljer vilka kalendrar som får användas. Avresan kan ligga före eller efter händelsens start och slut. En koppling kan begränsas till händelser vars beskrivning innehåller en text per uttag, t.ex. `MV1`. Se avsnitt 7.

**Nytt i 0.3.0:** kalenderkopplingar. Avresor hämtas automatiskt från en kalender i Home Assistant, till exempel en Google-kalender, med inställbar restid före händelsens start och/eller slut. Kalenderavresor kan hoppas över i kortet. Se avsnitt 7.

**Nytt i 0.2.1:** när ett relä är valt hamnar uttagets entiteter på reläets enhet, alltså Shellyn "Motorvärmare 1". Det blir då en enda enhet per uttag. Shelly-enheten behåller sitt namn och sitt område. Ett uttag utan relä får en egen enhet med uttagets namn.

## 1. Installera

**Via Marketplace (HACS), rekommenderat**

1. Öppna **Marketplace**, tryck på **⋮** och välj **Custom repositories**.
2. Fyll i URL `https://github.com/squarbe/ha-motorvarmare` och typ **Integration**. Klicka **Add**.
3. Sök efter **Motorvärmare** och välj **Download**. Starta om Home Assistant.

Nya versioner visas sedan som en uppdatering i Home Assistant.

**Manuellt:** kopiera `custom_components/motorvarmare` till `/config/custom_components/motorvarmare` och starta om.

Inga YAML-filer behövs.

## 2. Skapa integrationen och första uttaget

1. Gå till **Inställningar → Enheter och tjänster → Lägg till integration** och sök efter **Motorvärmare**. Integrationen kan bara läggas till en gång.
2. Öppna integrationen och välj **Lägg till motorvärmaruttag**. Fyll i:
   - **Namn:** `Motorvärmare 1`. Namnet används i larm och på kortet. När ett relä är valt följer entitets-id:na Shelly-enhetens namn (och troligen området, se avsnitt 4).
   - **Utomhustemperatur:** `sensor.utomhus_temperatur_temperature`
   - **Relä:** `switch.utomhus_motorvarmare_1` (respektive `_2`).
   - **Styr reläet på riktigt:** **AV** (testläge) under betatestet.
   - **Shellyns Auto Off:** 240. Ska vara samma värde som du ställer in i Shellyn.
   - **Larm skickas till:** en eller flera telefoner (`notify.mobile_app_…`) som får larm för just detta uttag. Lämna tomt för att använda integrationens gemensamma mottagare.
   - **Uppvärmningskurva:** standardvärdena ger 60 − 3 × temperatur, samma som din nuvarande mallhjälpare, men begränsad till 0–240 min.
3. Ändra ett uttag senare via de tre punkterna på uttaget → **Konfigurera om**. Fler uttag läggs till på samma sätt som det första.
4. **Inställningar** (kugghjulet på integrationen):
   - **Gemensam larmmottagare:** används för uttag som inte har egna larmmottagare. Larm visas alltid även som avisering i Home Assistant.
   - **Kalendrar som får användas:** t.ex. Förskola och Familj. Bara dessa går att välja i en kalenderkoppling. Lämna tomt för att tillåta alla.

## 3. Kortet

Kortet följer med integrationen. Du behöver inte kopiera något till `www`.

1. **Inställningar → Instrumentpaneler → ⋮ → Resurser → Lägg till resurs**
   - URL: `/motorvarmare/motorvarmare-card.js?v=0.5.0`
   - Typ: JavaScript-modul
2. Ladda om appen eller webbläsaren.
3. Lägg till kortet **Motorvärmare** från kortväljaren. Välj uttag i kortets redigerare: **Alla uttag** eller ett visst uttag.

**Alla uttag, rekommenderat.** Det här räcker att klistra in i en ny sektion:

```yaml
type: custom:motorvarmare-card
```

Kortet visar ett block per uttag, sorterat på namn. Ett uttag som läggs till senare i integrationen visas automatiskt.

**Ett visst uttag** (valfri rubrik):

```yaml
type: custom:motorvarmare-card
entity: sensor.<uttag>_avresor
title: Bil 1
```

Kortet visar status, uppvärmningstid, utetemperatur, effekt (från reläets enhet, t.ex. Shellyns Power), nästa start, avresor med lägg till/ändra/ta bort eller hoppa över, säkerhetsspärr med kvittering och forcerad start.

Byt `?v=` i resursens URL vid uppdatering av integrationen, så att webbläsaren hämtar det nya kortet.

## 4. Entiteter per uttag

`<uttag>` är det id-prefix som HA ger entiteterna. I testmiljön (HA 2026.10) blev det `motorvarmare_1`. I din HA 2026.11 kan områdets namn komma med, alltså `utomhus_motorvarmare_1`, på samma sätt som för reläet (K). Kontrollera på Shelly-enheten efter installationen.

| Entitet | Innehåll |
|---|---|
| `binary_sensor.<uttag>_varmebehov` | Värmebehov (PÅ/AV) |
| `binary_sensor.<uttag>_sakerhetssparr` | Säkerhetsspärr, med attributen orsak och tidpunkt |
| `sensor.<uttag>_status` | Klartextstatus |
| `sensor.<uttag>_uppvarmningstid` | Beräknad tid i minuter, med beräkningstemperatur och temperaturkälla |
| `sensor.<uttag>_avresor` | Antal avresor. Attributen används av kortet och sparas inte i historiken |
| `sensor.<uttag>_nasta_start` | Nästa planerade start. Attributet `preliminar` är sant när starten ligger mer än 4 h fram |
| `button.<uttag>_kvittera_sparr` | Kvittera spärr |
| `button.<uttag>_stoppa_forcering` | Stoppa forcerad start |

Ingen entitet har `state_class`, så inget hamnar i långtidsstatistiken.

## 5. Säkerhetsregler i live-läge

- **S1:** Reläet slås aldrig på medan spärren är aktiv.
- **S2:** Om reläet beordrats PÅ och sedan är AV i 30 s i följd blir det spärr och larm, och reläet slås inte på igen. Ett kortare glapp ger ingen spärr. Om reläet inte slår till inom 30 s efter kommandot blir det också spärr.
- **S3:** Om reläet är AV efter en omstart trots att det var beordrat PÅ, blir det spärr och larm. Om tiden ändå hade gått ut (se S4) spärras resten av behovsperioden, men utan larm. Fanns inget utestående PÅ-kommando startar uppvärmningen som vanligt efter omstart.
- **S4:** Integrationen slår själv av 5 min före Auto Off och slår inte på igen under samma behovsperiod. Auto Off ska alltså aldrig behöva lösa ut.
- **S5:** Kvittering startar aldrig uttaget. Det startar igen först vid nästa behovsperiod eller vid en forcerad start.
- **S6:** Ett otillgängligt relä räknas inte som AV. Inga kommandon skickas, och du får en varning efter 2 min om det finns ett värmebehov.

I testläge skickas inga kommandon. Ett undantag: om du byter från live- till testläge medan integrationen själv har reläet påslaget, slås det av en gång.

## 6. Avresor

- Värmebehovet startar vid avresa minus uppvärmningstid och upphör vid avresa + 60 min.
- När värmningen väl har startat avbryts den inte om temperaturen stiger.
- **Ändra en pågående avresa:** flyttas den så långt fram att starttiden hamnar i framtiden planeras den om och behovet upphör tills dess. Annars fortsätter behovet.
- **Tid utan tidszon** i tjänsteanrop tolkas som lokal tid.

### Beräkning och visning av starttid

- **Hysteres:** uppvärmningstiden räknas om först när utetemperaturen har ändrats minst 0,5 °C sedan förra beräkningen. Med 3 min/°C motsvarar det 1,5 min. Normal pendling i givaren ger alltså inga nya värden.
- **Aldrig för sent:** startbeslutet använder den längsta av den exakta och den publicerade uppvärmningstiden. Hysteresen kan därför aldrig göra att uttaget startar senare än exakt beräknat.
- **Sista 15 minuterna före start:** exakt temperatur utan hysteres, så att den visade tiden stämmer med när reläet slår till.
- **Mer än 4 timmar före start:** starttiden är **preliminär**. Den visas exakt men uppdateras högst var 15:e minut, eller direkt om temperaturen ändrats minst 1 °C. Kortet visar "(preliminär)". Inom 4 timmar följer den beräkningen.
- Den senast giltiga temperaturen sparas på disk först vid en ändring på minst 0,5 °C, eller var 5:e minut.

## 7. Kalenderkopplingar

Öppna integrationen och välj **Lägg till kalenderkoppling**. Lägg till en koppling per kalender.

**Steg 1**

- **Namn:** t.ex. `Förskola`. Visas i kortet.
- **Kalender:** någon av de kalendrar som får användas, t.ex. en Google-kalender.
- **Uttag:** ett eller flera uttag.
- **Vilka händelser:**
  - *Alla händelser med klockslag*
  - *Bara händelser med text i beskrivningen.* Ger ett steg 2.
- **Avresa vid händelsens start:** antal minuter, och om avresan ligger *före* eller *efter* starten.
- **Avresa vid händelsens slut:** ger en extra avresa. Antal minuter och *före* eller *efter* slutet.

**Steg 2 (bara med text):** ett fält per valt uttag, t.ex. `MV1` för Motorvärmare 1 och `MV2` för Motorvärmare 2. En händelse blir en avresa för ett uttag bara om dess **beskrivning** innehåller uttagets text.

- Texten måste stå som eget ord: `MV1` matchar inte `MV12`.
- Stora och små bokstäver spelar ingen roll.
- Står båda texterna i beskrivningen gäller avresan båda uttagen.
- Lämna fältet tomt för ett uttag som kalendern inte ska styra.

**Exempel**

- **Förskola:** alla händelser, start 15 min före, slut 15 min före. En händelse 08:00–16:00 ger avresorna 07:45 och 15:45.
- **Familj:** bara med text, `MV1` / `MV2`, start 0 min före. Skriv `MV1` i beskrivningen på de händelser som ska värma bil 1.

**Regler**

- Heldagshändelser ignoreras alltid.
- Kalendern läses var 5:e minut och när kalenderentiteten ändras, två dygn framåt. Tjänsten `motorvarmare.refresh_calendars` läser om direkt.
- **Vid uppstart** läses kalendrarna först när HA har startat helt. Är kalendern inte klar, till exempel för att Google inte har synkat än, görs nya försök efter 30 s, 1, 2, 4 och sedan var 5:e minut. Under de första 10 minuterna loggas det bara på debug-nivå. Går kalendern fortfarande inte att läsa efter det kommer en varning, en gång per felorsak.
- En kalenderavresa ligger kvar till 60 min efter avresetiden, precis som en manuell.
- Överlappande avresor bryter inte varandra: när den första avresans 60 min har gått ut fortsätter en redan startad senare avresa utan avbrott.
- Tas händelsen bort ur kalendern innan uppvärmningen har startat försvinner avresan. Har den startat fortsätter den.
- Går kalendern inte att läsa, t.ex. direkt efter omstart, behålls de avresor som redan finns.
- En kalenderavresa ändras i kalendern, inte i kortet. I kortet kan den **hoppas över** och **återställas**. Överhoppningen gäller bara det uttaget.
- Ändras händelsens tid eller titel räknas den som en ny avresa. En tidigare överhoppning gäller då inte längre.
- Sensorn Avresor räknar inte överhoppade avresor.

## 8. Inte med i 0.7

- Historik över borttagna avresor

## Tester

Testerna kräver Python 3.14 och `pytest-homeassistant-custom-component`. Kör `pytest` i repots rot.
