# Mask Bridge - Detection Classes

RF-DETR detects **80 object classes** from the COCO dataset. Here is the complete list you can use in the Advanced Settings.

---

## 🚗 Transport (9 classes)

| Class | Keywords |
|-------|----------|
| person | person, human |
| bicycle | bicycle, bike |
| car | car, automobile |
| motorcycle | motorcycle, moto |
| airplane | airplane, plane |
| bus | bus |
| train | train |
| truck | truck |
| boat | boat |

---

## 🐾 Animals (10 classes)

| Class | Keywords |
|-------|----------|
| bird | bird |
| cat | cat |
| dog | dog |
| horse | horse |
| sheep | sheep |
| cow | cow |
| elephant | elephant |
| bear | bear |
| zebra | zebra |
| giraffe | giraffe |

---

## 🪑 Furniture & Interior (6 classes)

| Class | Keywords |
|-------|----------|
| bench | bench |
| chair | chair |
| couch | couch, sofa |
| bed | bed |
| dining table | table, dining table |
| toilet | toilet |

---

## 📺 Electronics (8 classes)

| Class | Keywords |
|-------|----------|
| tv | tv, television |
| laptop | laptop, computer |
| mouse | mouse |
| remote | remote |
| keyboard | keyboard |
| cell phone | phone, cell phone |
| microwave | microwave |
| oven | oven |

---

## 🎒 Accessories (6 classes)

| Class | Keywords |
|-------|----------|
| backpack | backpack |
| umbrella | umbrella |
| handbag | handbag, purse |
| tie | tie |
| suitcase | suitcase, luggage |
| frisbee | frisbee |

---

## ⚽ Sports & Leisure (9 classes)

| Class | Keywords |
|-------|----------|
| skis | skis |
| snowboard | snowboard |
| sports ball | ball |
| kite | kite |
| baseball bat | baseball bat |
| baseball glove | baseball glove |
| skateboard | skateboard |
| surfboard | surfboard |
| tennis racket | tennis racket |

---

## 🍎 Food (17 classes)

| Class | Keywords |
|-------|----------|
| bottle | bottle |
| wine glass | wine glass, glass |
| cup | cup, mug |
| fork | fork |
| knife | knife |
| spoon | spoon |
| bowl | bowl |
| banana | banana |
| apple | apple |
| sandwich | sandwich |
| orange | orange |
| broccoli | broccoli |
| carrot | carrot |
| hot dog | hot dog |
| pizza | pizza |
| donut | donut |
| cake | cake |

---

## 🏠 Other Objects (15 classes)

| Class | Keywords |
|-------|----------|
| traffic light | traffic light |
| fire hydrant | fire hydrant |
| stop sign | stop sign |
| parking meter | parking meter |
| potted plant | plant, potted plant |
| toaster | toaster |
| sink | sink |
| refrigerator | refrigerator, fridge |
| book | book |
| clock | clock |
| vase | vase |
| scissors | scissors |
| teddy bear | teddy bear, plush |
| hair drier | hair drier |
| toothbrush | toothbrush |

---

## ⚠️ Limitations

**NOT detectable by RF-DETR:**
- Cables / wires
- Buildings / houses
- Trees (except "potted plant")
- Skies / clouds
- Roads / sidewalks
- Mountains / landscapes

---

## 💡 Usage in Mask Bridge

In the **Advanced Settings** section, type the classes separated by commas:

```
person, car, dog
```

### 🧠 Smart Categories (Macro)
You can use these generic terms to select multiple classes at once:

| Keyword | Detects |
|---------|---------|
| **vehicle** | car, motorcycle, bus, train, truck |
| **animal** | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| **furniture** | chair, couch, bed, dining table, bench, toilet |
| **electronics** | tv, laptop, mouse, remote, keyboard, phone |
| **sports** | all sports gear + skateboard, surfboard, tennis racket |
| **plant** | potted plant (vegetation) |
