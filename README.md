# Rețele Electrice (McG)

Integrare Home Assistant independentă pentru portalul `contulmeu.reteleelectrice.ro`.
Nu folosește server de licențiere, cheie de activare, perioadă de probă sau
telemetrie proprie. Contul și parola sunt păstrate numai în configurația locală
Home Assistant și sunt trimise exclusiv portalului Rețele Electrice pentru
autentificare.

## Entități

Entitățile sunt create condiționat, numai când portalul returnează datele:

- Informații POD și date furnizor;
- index consum și, pentru prosumatori, index producție;
- arhivă anuală de energie consumată/produsă;
- stare întreruperi de curent;
- Smart Meter consum/producție;
- valori instantanee consum/producție;
- buton pentru actualizarea valorilor instantanee.

Când operatorul activează ulterior Smart Meter sau valorile instantanee, noile
entități sunt descoperite automat la o actualizare. Nu trebuie reinstalată
integrarea.

## Instalare manuală

### Prin HACS / Marketplace

1. Adaugă `https://github.com/McG04/retele-electrice-mcg-home-assistant`
   ca repository personalizat de tip **Integration**.
2. Instalează **Rețele Electrice (McG)** și repornește Home Assistant.
3. Deschide **Setări → Dispozitive și servicii → Adaugă integrare**.

### Manual

1. Copiază folderul `custom_components/retele_electrice_local` în
   `/config/custom_components/`.
2. Repornește Home Assistant.
3. Deschide **Setări → Dispozitive și servicii → Adaugă integrare**.
4. Caută **Rețele Electrice (McG)**.
5. Introdu emailul și parola contului.
6. Alege POD-ul din lista încărcată automat din portal.

Intervalul implicit este de o oră. Poate fi schimbat între o oră și 24 de ore
din opțiunile integrării.

## Observații

Portalul Rețele Electrice este o aplicație Salesforce fără API public stabil.
Integrarea reproduce doar cererile folosite de portalul clientului. O schimbare
a formularelor Salesforce sau a serviciilor Visualforce poate necesita o
actualizare a componentei.

Acest proiect este independent și nu este afiliat cu Rețele Electrice România.

## Versiuni

- **0.2.3** — parametri Visualforce corectați pentru furnizor, arhivă,
  întreruperi și Smart Meter; integrarea rămâne activă când portalul oferă
  datele POD prin Aura, dar un serviciu secundar este temporar indisponibil.
