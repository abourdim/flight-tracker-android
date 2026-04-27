# Play Store listing — Flight Tracker (متتبع الطائرات)

Draft copy for Google Play Console "Main store listing" page. Play Console accepts separate translations per language — upload all three.

---

## Metadata (common to all languages)

- **Package name**: `org.workshopdiy.flighttracker`
- **Category**: `Books & Reference` (primary), `Education` (secondary if allowed)
- **Tags**: Islamic studies, Arabic, trilingual, education, al-Ghazali
- **Contact email**: `abdelhak.bourdim@gmail.com`
- **Website**: `https://workshop-diy.org`
- **Privacy policy URL**: REQUIRED — host a simple page (see template at end of this file).
- **Content rating**: Everyone (no violence, no gambling, no mature content).
- **Ads**: No.
- **In-app purchases**: No.
- **Data safety**: No data collected, no data shared.

---

## Arabic (ar) — primary

### App name (≤30 chars)
```
متتبع الطائرات
```

### Short description (≤80 chars)
```
متتبع الطائرات — micro:bit & بلوتوث
```

### Full description (≤4000 chars)
```
✈ متتبع الطائرات

تطبيق تفاعلي يربط بلوحة BBC micro:bit V2 عبر البلوتوث منخفض الطاقة (BLE). للأطفال ومحبي التكنولوجيا.

✨ المزايا
• اتصال BLE
• واجهة تفاعلية
• ثلاث لغات: عربية، إنجليزية، فرنسية
• يعمل بدون اتصال بالإنترنت

من workshop-diy.org
```

---

## English (en)

### App name
```
Flight Tracker — Planes in the Sky
```

### Short description
```
Planes in the Sky — micro:bit BLE app for kids
```

### Full description
```
✈ Planes in the Sky

Interactive web app that pairs with a BBC micro:bit V2 over Bluetooth Low Energy. Part of the workshop-diy.org series.

✨ Features
• BLE connection
• Interactive UI
• Three languages: Arabic, English, French
• Works offline

From workshop-diy.org
```

---

## French (fr)

### App name
```
Flight Tracker — Planes in the Sky
```

### Short description
```
Planes in the Sky — application micro:bit BLE
```

### Full description
```
✈ Planes in the Sky

Application interactive qui se connecte à un BBC micro:bit V2 via Bluetooth Low Energy. Partie de la série workshop-diy.org.

✨ Fonctionnalités
• Connexion BLE
• Interface interactive
• Trois langues: arabe, anglais, français
• Fonctionne hors ligne

De workshop-diy.org
```

---

## Graphics needed (minimum)

| Asset | Size | Source |
|---|---|---|
| App icon | 512×512 PNG | `store-assets/play-store-icon-512.png` (regenerate per book) |
| Feature graphic | 1024×500 PNG | `store-assets/feature-graphic.png` (render from `feature-graphic.html`) |
| Phone screenshots | min 2, 320–3840px, 16:9 portrait | Capture from emulator / real device |
| 7" tablet screenshots (optional) | min 2, 1024×600+ | Run emulator with tablet profile |

Screenshots to capture (book-specific — adjust list to actual app screens):
1. Home / cover / introduction
2. Main content navigation
3. Reading or interaction mode
4. Quiz or self-assessment (if applicable)
5. Theme switch (optional — shows the 3 variants)

---

## Privacy policy template

Copy to a public page (GitHub Pages works). Change email + date.

```
Privacy Policy — Flight Tracker
Last updated: 2026-04-27

The Flight Tracker app does not collect, store, transmit, or share any personal
data. All content is bundled with the app and runs entirely on your device.
The app does not use analytics, advertising networks, crash reporters, or
third-party SDKs.

The app requires no special permissions beyond internet access, which is
used only to load the occasional external link (e.g. workshop-diy.org) if
you tap it — never silently in the background.

If you have questions, contact: abdelhak.bourdim@gmail.com
```
