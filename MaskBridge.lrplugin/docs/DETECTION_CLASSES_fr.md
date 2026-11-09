# Mask Bridge - Classes de Détection

RF-DETR détecte **80 classes d'objets** issues du jeu de données COCO. Voici la liste complète que vous pouvez utiliser dans les Paramètres Avancés.

⚠️ **Important :** Le moteur d'IA utilise ces mots-clés en anglais. Vous devez donc saisir les termes originaux (en anglais) dans le plugin.

---

## 🚗 Transport (9 classes)

| Classe (anglais) | Traduction / Mots-clés |
|------------------|------------------------|
| person | personne, humain |
| bicycle | vélo, bicyclette |
| car | voiture, automobile |
| motorcycle | moto, motocyclette |
| airplane | avion |
| bus | bus |
| train | train |
| truck | camion |
| boat | bateau |

---

## 🐾 Animaux (10 classes)

| Classe (anglais) | Traduction / Mots-clés |
|------------------|------------------------|
| bird | oiseau |
| cat | chat |
| dog | chien |
| horse | cheval |
| sheep | mouton |
| cow | vache |
| elephant | éléphant |
| bear | ours |
| zebra | zèbre |
| giraffe | girafe |

---

## 🪑 Mobilier & Intérieur (6 classes)

| Classe (anglais) | Traduction / Mots-clés |
|------------------|------------------------|
| bench | banc |
| chair | chaise |
| couch | canapé, sofa |
| bed | lit |
| dining table | table à manger |
| toilet | toilettes |

---

## 📺 Électronique (8 classes)

| Classe (anglais) | Traduction / Mots-clés |
|------------------|------------------------|
| tv | télévision, télé |
| laptop | ordinateur portable |
| mouse | souris (ordinateur) |
| remote | télécommande |
| keyboard | clavier |
| cell phone | téléphone portable |
| microwave | micro-ondes |
| oven | four |

---

## 🎒 Accessoires (6 classes)

| Classe (anglais) | Traduction / Mots-clés |
|------------------|------------------------|
| backpack | sac à dos |
| umbrella | parapluie |
| handbag | sac à main |
| tie | cravate |
| suitcase | valise, bagage |
| frisbee | frisbee |

---

## ⚽ Sports & Loisirs (9 classes)

| Classe (anglais) | Traduction / Mots-clés |
|------------------|------------------------|
| skis | skis |
| snowboard | snowboard |
| sports ball | ballon, balle |
| kite | cerf-volant |
| baseball bat | batte de baseball |
| baseball glove | gant de baseball |
| skateboard | skateboard |
| surfboard | planche de surf |
| tennis racket | raquette de tennis |

---

## 🍎 Nourriture (17 classes)

| Classe (anglais) | Traduction / Mots-clés |
|------------------|------------------------|
| bottle | bouteille |
| wine glass | verre à vin, verre |
| cup | tasse, mug |
| fork | fourchette |
| knife | couteau |
| spoon | cuillère |
| bowl | bol |
| banana | banane |
| apple | pomme |
| sandwich | sandwich |
| orange | orange |
| broccoli | brocoli |
| carrot | carotte |
| hot dog | hot dog |
| pizza | pizza |
| donut | donut |
| cake | gâteau |

---

## 🏠 Autres Objets (15 classes)

| Classe (anglais) | Traduction / Mots-clés |
|------------------|------------------------|
| traffic light | feu de signalisation |
| fire hydrant | bouche d'incendie |
| stop sign | panneau stop |
| parking meter | parcmètre |
| potted plant | plante en pot |
| toaster | grille-pain |
| sink | évier, lavabo |
| refrigerator | réfrigérateur, frigo |
| book | livre |
| clock | horloge, montre |
| vase | vase |
| scissors | ciseaux |
| teddy bear | ours en peluche |
| hair drier | sèche-cheveux |
| toothbrush | brosse à dents |

---

## ⚠️ Limites

**NON détectable par RF-DETR :**
- Câbles / fils
- Bâtiments / maisons
- Arbres (sauf "potted plant")
- Ciel / nuages
- Routes / trottoirs
- Montagnes / paysages

---

## 💡 Utilisation dans Mask Bridge

Dans la section **Paramètres Avancés**, tapez les classes en anglais séparées par des virgules :

```
person, car, dog
```

### 🧠 Catégories Intelligentes (Macro)
Vous pouvez utiliser ces termes génériques pour sélectionner plusieurs classes à la fois :

| Mot-clé | Détecte |
|---------|---------|
| **vehicle** | car, motorcycle, bus, train, truck |
| **animal** | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| **furniture** | chair, couch, bed, dining table, bench, toilet |
| **electronics** | tv, laptop, mouse, remote, keyboard, phone |
| **sports** | tous les équipements de sport + skateboard, surfboard, tennis racket |
| **plant** | potted plant (végétation) |
