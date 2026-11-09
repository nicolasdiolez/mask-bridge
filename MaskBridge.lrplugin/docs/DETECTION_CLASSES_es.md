# Mask Bridge - Clases de Detección

RF-DETR detecta **80 clases de objetos** del conjunto de datos COCO. Aquí está la lista completa que puede usar en la Configuración Avanzada.

⚠️ **Importante:** El motor de IA utiliza estos términos en inglés. Por lo tanto, debe ingresar los términos originales (en inglés) en el plugin.

---

## 🚗 Transporte (9 clases)

| Clase (inglés) | Traducción / Palabras clave |
|----------------|-----------------------------|
| person | persona, humano |
| bicycle | bicicleta, bici |
| car | coche, automóvil |
| motorcycle | motocicleta, moto |
| airplane | avión |
| bus | autobús |
| train | tren |
| truck | camión |
| boat | barco |

---

## 🐾 Animales (10 clases)

| Clase (inglés) | Traducción / Palabras clave |
|----------------|-----------------------------|
| bird | pájaro, ave |
| cat | gato |
| dog | perro |
| horse | caballo |
| sheep | oveja |
| cow | vaca |
| elephant | elefante |
| bear | oso |
| zebra | cebra |
| giraffe | jirafa |

---

## 🪑 Muebles e Interior (6 clases)

| Clase (inglés) | Traducción / Palabras clave |
|----------------|-----------------------------|
| bench | banco |
| chair | silla |
| couch | sofá |
| bed | cama |
| dining table | mesa de comedor |
| toilet | inodoro, baño |

---

## 📺 Electrónica (8 clases)

| Clase (inglés) | Traducción / Palabras clave |
|----------------|-----------------------------|
| tv | televisión, tv |
| laptop | computadora portátil |
| mouse | ratón (computadora) |
| remote | mando a distancia |
| keyboard | teclado |
| cell phone | teléfono móvil, celular |
| microwave | microondas |
| oven | horno |

---

## 🎒 Accesorios (6 clases)

| Clase (inglés) | Traducción / Palabras clave |
|----------------|-----------------------------|
| backpack | mochila |
| umbrella | paraguas |
| handbag | bolso |
| tie | corbata |
| suitcase | maleta, equipaje |
| frisbee | frisbee |

---

## ⚽ Deportes y Ocio (9 clases)

| Clase (inglés) | Traducción / Palabras clave |
|----------------|-----------------------------|
| skis | esquís |
| snowboard | tabla de snowboard |
| sports ball | pelota, balón de deportes |
| kite | cometa |
| baseball bat | bate de béisbol |
| baseball glove | guante de béisbol |
| skateboard | monopatín |
| surfboard | tabla de surf |
| tennis racket | raqueta de tenis |

---

## 🍎 Comida (17 clases)

| Clase (inglés) | Traducción / Palabras clave |
|----------------|-----------------------------|
| bottle | botella |
| wine glass | copa de vino |
| cup | taza |
| fork | tenedor |
| knife | cuchillo |
| spoon | cuchara |
| bowl | tazón, cuenco |
| banana | plátano |
| apple | manzana |
| sandwich | sándwich |
| orange | naranja |
| broccoli | brócoli |
| carrot | zanahoria |
| hot dog | perrito caliente |
| pizza | pizza |
| donut | rosquilla, donut |
| cake | pastel |

---

## 🏠 Otros Objetos (15 clases)

| Clase (inglés) | Traducción / Palabras clave |
|----------------|-----------------------------|
| traffic light | semáforo |
| fire hydrant | boca de incendios |
| stop sign | señal de stop |
| parking meter | parquímetro |
| potted plant | planta en maceta |
| toaster | tostadora |
| sink | fregadero, lavabo |
| refrigerator | refrigerador, nevera |
| book | libro |
| clock | reloj |
| vase | jarrón |
| scissors | tijeras |
| teddy bear | oso de peluche |
| hair drier | secador de pelo |
| toothbrush | cepillo de dientes |

---

## ⚠️ Limitaciones

**NO detectable por RF-DETR:**
- Cables / hilos
- Edificios / casas
- Árboles (excepto "potted plant")
- Cielos / nubes
- Carreteras / aceras
- Montañas / paisajes

---

## 💡 Uso en Mask Bridge

En la sección de **Configuración Avanzada**, escriba las clases en inglés separadas por comas:

```
person, car, dog
```

### 🧠 Categorías Inteligentes (Macro)
Puede usar estos términos genéricos para seleccionar varias clases a la vez:

| Palabra clave | Detecta |
|---------------|---------|
| **vehicle** | car, motorcycle, bus, train, truck |
| **animal** | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| **furniture** | chair, couch, bed, dining table, bench, toilet |
| **electronics** | tv, laptop, mouse, remote, keyboard, phone |
| **sports** | todo el equipo deportivo + skateboard, surfboard, tennis racket |
| **plant** | potted plant (vegetación) |
