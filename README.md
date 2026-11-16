# Motorvärmare

Egen Home Assistant-integration för motorvärmare: avresor, temperaturberoende uppvärmningstid och säker styrning av Shelly-reläer. Version 0.3.0, betatest.

Ersätter beta 0.1.0, som aldrig installerades. Den här versionen är **en** integration. Varje motorvärmaruttag läggs till som en underpost.

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
   - **Uppvärmningskurva:** standardvärdena ger 60 − 3 × temperatur, samma som din nuvarande mallhjälpare, men begränsad till 0–240 min.
3. Ändra ett uttag senare via de tre punkterna på uttaget → **Konfigurera om**. Fler uttag läggs till på samma sätt som det första.
4. **Larm:** öppna integrationens inställningar (kugghjulet) och välj din telefons `notify.mobile_app_…`. Larm visas alltid även som avisering i Home Assistant.

## 3. Kortet

Kortet följer med integrationen. Du behöver inte kopiera något till `www`.

1. **Inställningar → Instrumentpaneler → ⋮ → Resurser → Lägg till resurs**
   - URL: `/motorvarmare/motorvarmare-card.js`
   - Typ: JavaScript-modul
2. Ladda om appen eller webbläsaren.
3. Lägg till kortet **Motorvärmare** från kortväljaren, eller använd manuellt:

```yaml
type: custom:motorvarmare-card
entity: sensor.<uttag>_avresor
```

Den faktiska `entity` ser du på Shelly-enheten under **Avresor** (se avsnitt 4). Kortets väljare föreslår den automatiskt.

## 4. Entiteter per uttag

`<uttag>` är det id-prefix som HA ger entiteterna. I testmiljön (HA 2026.10) blev det `motorvarmare_1`. I din HA 2026.11 kan områdets namn komma med, alltså `utomhus_motorvarmare_1`, på samma sätt som för reläet (K). Kontrollera på Shelly-enheten efter installationen.

| Entitet | Innehåll |
|---|---|
| `binary_sensor.<uttag>_varmebehov` | Värmebehov (PÅ/AV) |
| `binary_sensor.<uttag>_sakerhetssparr` | Säkerhetsspärr, med attributen orsak och tidpunkt |
| `sensor.<uttag>_status` | Klartextstatus |
| `sensor.<uttag>_uppvarmningstid` | Beräknad tid i minuter, med temperaturkälla |
| `sensor.<uttag>_avresor` | Antal avresor. Attributen används av kortet och sparas inte i historiken |
| `sensor.<uttag>_nasta_start` | Nästa planerade start |
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

## 7. Kalenderkopplingar

Öppna integrationen och välj **Lägg till kalenderkoppling**. Lägg till en koppling per kalender. Fyll i:

- **Namn:** t.ex. `Förskola`. Visas i kortet.
- **Kalender:** vilken kalenderentitet som helst i HA, t.ex. en Google-kalender.
- **Uttag:** ett eller flera uttag som ska värmas för kalenderns händelser.
- **Avresa vid händelsens start** och **Restid före start:** avresetid = start − restid.
- **Avresa vid händelsens slut** och **Restid före slut:** ger en extra avresa, t.ex. för hämtning. Avresetid = slut − restid.

Exempel, förskola: start på, restid 15 min, slut på, restid 15 min. En händelse 08:00–16:00 ger avresorna 07:45 och 15:45.

Regler:

- Alla händelser med klockslag blir avresor. Heldagshändelser ignoreras.
- Kalendern läses var 5:e minut och när kalenderentiteten ändras, två dygn framåt. Tjänsten `motorvarmare.refresh_calendars` läser om direkt.
- En kalenderavresa ligger kvar till 60 min efter avresetiden, precis som en manuell.
- Tas händelsen bort ur kalendern innan uppvärmningen har startat försvinner avresan. Har uppvärmningen startat fortsätter den.
- Går kalendern inte att läsa, t.ex. direkt efter omstart, behålls de avresor som redan finns.
- En kalenderavresa ändras i kalendern, inte i kortet. I kortet kan den **hoppas över** och **återställas**. En överhoppad avresa ger inget värmebehov. Hoppar du över en pågående avresa upphör behovet.
- Ändras händelsens tid eller titel räknas den som en ny avresa. En tidigare överhoppning gäller då inte längre.
- Sensorn Avresor räknar inte överhoppade avresor.

## 8. Inte med i 0.3

- Historik över borttagna avresor

## Tester

Testerna kräver Python 3.14 och `pytest-homeassistant-custom-component`. Kör `pytest` i repots rot.
