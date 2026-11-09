# Mask Bridge - Erkennungsklassen

RF-DETR erkennt **80 Objektklassen** aus dem COCO-Datensatz. Hier ist die vollständige Liste, die Sie in den Erweiterten Einstellungen verwenden können.

⚠️ **Wichtig:** Die KI-Engine verwendet diese englischen Begriffe. Daher müssen Sie die Originalbegriffe (auf Englisch) in das Plugin eingeben.

---

## 🚗 Verkehrsmittel (9 Klassen)

| Klasse (Englisch) | Übersetzung / Schlüsselwörter |
|-------------------|-------------------------------|
| person | Person, Mensch |
| bicycle | Fahrrad |
| car | Auto |
| motorcycle | Motorrad |
| airplane | Flugzeug |
| bus | Bus |
| train | Zug |
| truck | LKW, Lastwagen |
| boat | Boot |

---

## 🐾 Tiere (10 Klassen)

| Klasse (Englisch) | Übersetzung / Schlüsselwörter |
|-------------------|-------------------------------|
| bird | Vogel |
| cat | Katze |
| dog | Hund |
| horse | Pferd |
| sheep | Schaf |
| cow | Kuh |
| elephant | Elefant |
| bear | Bär |
| zebra | Zebra |
| giraffe | Giraffe |

---

## 🪑 Möbel und Inneneinrichtung (6 Klassen)

| Klasse (Englisch) | Übersetzung / Schlüsselwörter |
|-------------------|-------------------------------|
| bench | Bank |
| chair | Stuhl |
| couch | Couch, Sofa |
| bed | Bett |
| dining table | Esstisch |
| toilet | Toilette |

---

## 📺 Elektronik (8 Klassen)

| Klasse (Englisch) | Übersetzung / Schlüsselwörter |
|-------------------|-------------------------------|
| tv | Fernseher, TV |
| laptop | Laptop, Notebook |
| mouse | Maus |
| remote | Fernbedienung |
| keyboard | Tastatur |
| cell phone | Handy, Smartphone |
| microwave | Mikrowelle |
| oven | Ofen, Backofen |

---

## 🎒 Accessoires (6 Klassen)

| Klasse (Englisch) | Übersetzung / Schlüsselwörter |
|-------------------|-------------------------------|
| backpack | Rucksack |
| umbrella | Regenschirm |
| handbag | Handtasche |
| tie | Krawatte |
| suitcase | Koffer |
| frisbee | Frisbee |

---

## ⚽ Sport und Freizeit (9 Klassen)

| Klasse (Englisch) | Übersetzung / Schlüsselwörter |
|-------------------|-------------------------------|
| skis | Ski |
| snowboard | Snowboard |
| sports ball | Ball, Sportball |
| kite | Drachen |
| baseball bat | Baseballschläger |
| baseball glove | Baseballhandschuh |
| skateboard | Skateboard |
| surfboard | Surfbrett |
| tennis racket | Tennisschläger |

---

## 🍎 Lebensmittel (17 Klassen)

| Klasse (Englisch) | Übersetzung / Schlüsselwörter |
|-------------------|-------------------------------|
| bottle | Flasche |
| wine glass | Weinglas |
| cup | Tasse, Becher |
| fork | Gabel |
| knife | Messer |
| spoon | Löffel |
| bowl | Schüssel |
| banana | Banane |
| apple | Apfel |
| sandwich | Sandwich |
| orange | Orange |
| broccoli | Brokkoli |
| carrot | Karotte |
| hot dog | Hotdog |
| pizza | Pizza |
| donut | Donut |
| cake | Kuchen |

---

## 🏠 Andere Objekte (15 Klassen)

| Klasse (Englisch) | Übersetzung / Schlüsselwörter |
|-------------------|-------------------------------|
| traffic light | Ampel |
| fire hydrant | Hydrant |
| stop sign | Stoppschild |
| parking meter | Parkuhr |
| potted plant | Topfpflanze |
| toaster | Toaster |
| sink | Waschbecken, Spülbecken |
| refrigerator | Kühlschrank |
| book | Buch |
| clock | Uhr |
| vase | Vase |
| scissors | Schere |
| teddy bear | Teddybär |
| hair drier | Haartrockner, Föhn |
| toothbrush | Zahnbürste |

---

## ⚠️ Einschränkungen

**NICHT durch RF-DETR erkennbar:**
- Kabel / Drähte
- Gebäude / Häuser
- Bäume (außer "potted plant")
- Himmel / Wolken
- Straßen / Gehwege
- Berge / Landschaften

---

## 💡 Verwendung in Mask Bridge

Geben Sie im Abschnitt **Erweiterte Einstellungen** die englischen Klassen durch Kommas getrennt ein:

```
person, car, dog
```

### 🧠 Intelligente Kategorien (Makro)
Sie können diese generischen Begriffe verwenden, um mehrere Klassen gleichzeitig auszuwählen:

| Schlüsselwort | Erkennt |
|---------------|---------|
| **vehicle** | car, motorcycle, bus, train, truck |
| **animal** | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| **furniture** | chair, couch, bed, dining table, bench, toilet |
| **electronics** | tv, laptop, mouse, remote, keyboard, phone |
| **sports** | sämtliche Sportgeräte + skateboard, surfboard, tennis racket |
| **plant** | potted plant (Vegetation) |
