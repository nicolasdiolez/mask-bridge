# Mask Bridge - Classi di Rilevamento

RF-DETR rileva **80 classi di oggetti** dal dataset COCO. Ecco l'elenco completo che puoi utilizzare nelle Impostazioni Avanzate.

⚠️ **Importante:** Il motore AI utilizza questi termini in inglese. Pertanto, è necessario inserire i termini originali (in inglese) nel plugin.

---

## 🚗 Trasporti (9 classi)

| Classe (inglese) | Traduzione / Parole chiave |
|------------------|----------------------------|
| person | persona, umano |
| bicycle | bicicletta, bici |
| car | auto, macchina |
| motorcycle | motocicletta, moto |
| airplane | aereo |
| bus | autobus |
| train | treno |
| truck | camion |
| boat | barca |

---

## 🐾 Animali (10 classi)

| Classe (inglese) | Traduzione / Parole chiave |
|------------------|----------------------------|
| bird | uccello |
| cat | gatto |
| dog | cane |
| horse | cavallo |
| sheep | pecora |
| cow | mucca |
| elephant | elefante |
| bear | orso |
| zebra | zebra |
| giraffe | giraffa |

---

## 🪑 Mobili e Interni (6 classi)

| Classe (inglese) | Traduzione / Parole chiave |
|------------------|----------------------------|
| bench | panchina |
| chair | sedia |
| couch | divano |
| bed | letto |
| dining table | tavolo da pranzo |
| toilet | water, wc |

---

## 📺 Elettronica (8 classi)

| Classe (inglese) | Traduzione / Parole chiave |
|------------------|----------------------------|
| tv | tv, televisione |
| laptop | portatile, computer |
| mouse | mouse |
| remote | telecomando |
| keyboard | tastiera |
| cell phone | cellulare, telefono |
| microwave | microonde |
| oven | forno |

---

## 🎒 Accessori (6 classi)

| Classe (inglese) | Traduzione / Parole chiave |
|------------------|----------------------------|
| backpack | zaino |
| umbrella | ombrello |
| handbag | borsa |
| tie | cravatta |
| suitcase | valigia, bagaglio |
| frisbee | frisbee |

---

## ⚽ Sport e Tempo libero (9 classi)

| Classe (inglese) | Traduzione / Parole chiave |
|------------------|----------------------------|
| skis | sci |
| snowboard | snowboard |
| sports ball | palla, pallone |
| kite | aquilone |
| baseball bat | mazza da baseball |
| baseball glove | guanto da baseball |
| skateboard | skateboard |
| surfboard | tavola da surf |
| tennis racket | racchetta da tennis |

---

## 🍎 Cibo (17 classi)

| Classe (inglese) | Traduzione / Parole chiave |
|------------------|----------------------------|
| bottle | bottiglia |
| wine glass | bicchiere di vino |
| cup | tazza |
| fork | forchetta |
| knife | coltello |
| spoon | cucchiaio |
| bowl | ciotola |
| banana | banana |
| apple | mela |
| sandwich | panino |
| orange | arancia |
| broccoli | broccoli |
| carrot | carota |
| hot dog | hot dog |
| pizza | pizza |
| donut | ciambella |
| cake | torta |

---

## 🏠 Altri Oggetti (15 classi)

| Classe (inglese) | Traduzione / Parole chiave |
|------------------|----------------------------|
| traffic light | semaforo |
| fire hydrant | idrante |
| stop sign | segnale di stop |
| parking meter | parchimetro |
| potted plant | pianta in vaso |
| toaster | tostapane |
| sink | lavandino |
| refrigerator | frigorifero |
| book | libro |
| clock | orologio |
| vase | vaso |
| scissors | forbici |
| teddy bear | orsacchiotto |
| hair drier | asciugacapelli |
| toothbrush | spazzolino da denti |

---

## ⚠️ Limitazioni

**NON rilevabile da RF-DETR:**
- Cavi / fili
- Edifici / case
- Alberi (tranne "potted plant")
- Cieli / nuvole
- Strade / marciapiedi
- Montagne / paesaggi

---

## 💡 Uso in Mask Bridge

Nella sezione **Impostazioni Avanzate**, digita le classi in inglese separate da virgole:

```
person, car, dog
```

### 🧠 Categorie Intelligenti (Macro)
Puoi usare questi termini generici per selezionare più classi contemporaneamente:

| Parola chiave | Rileva |
|---------------|--------|
| **vehicle** | car, motorcycle, bus, train, truck |
| **animal** | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| **furniture** | chair, couch, bed, dining table, bench, toilet |
| **electronics** | tv, laptop, mouse, remote, keyboard, phone |
| **sports** | tutta l'attrezzatura sportiva + skateboard, surfboard, tennis racket |
| **plant** | potted plant (vegetazione) |
