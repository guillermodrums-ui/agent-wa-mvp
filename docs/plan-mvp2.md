Aquí tienes 3 ideas de features (To-Dos) ordenadas por impacto para el MVP v2:

1. El "Panel de Control de Tráfico" (Handoff UI)
Prioridad: ALTA 🔴

Ahora mismo, si conectás el WhatsApp real, el bot va a responder a todo. Si Mauri agarra su celular para contestar, el bot podría interrumpirlo o responder encima. Necesitamos un "Semáforo".

La Feature: Un switch en el Dashboard de Admin para cada chat activo que diga: [ 🟢 IA ACTIVA ] / [ 🔴 MODO HUMANO ].

Cómo funciona:

En la tabla sessions de SQLite, agregás una columna is_paused (boolean).

Si Mauri ve que un cliente se complica, entra al admin y pone el switch en ROJO (Pausado).

El agent.py verifica este flag antes de procesar cualquier mensaje. Si está en True, ignora el webhook.

Mauri chatea tranquilo desde su celular.

Cuando termina, vuelve a poner el switch en VERDE y Nico retoma la guardia.

Por qué suma: Le da el control total a Mauri. Es la característica que elimina el miedo a usar la IA.

2. Soporte de Notas de Voz (Audio-to-Text)
Prioridad: MEDIA 🟡

En Uruguay (y LATAM en general), la gente odia escribir. Te mandan audios de 2 minutos explicando su rutina de gimnasio. Si Nico responde: "No puedo escuchar audios", la magia se rompe.

La Feature: Integrar Whisper (OpenAI o Groq) para transcribir audios entrantes.

Arquitectura:

Evolution API te manda el link del archivo de audio en el webhook.

Tu backend descarga el .ogg.

Lo mandás a la API de Groq (Whisper-large-v3) (es rapidísima y casi gratis).

Recibís el texto: "Hola Mauri, che, sabés que la creatina me cayó pesada...".

Ese texto entra al flujo normal del Agente como si el usuario lo hubiera escrito.

En el prompt del sistema agregás: "El usuario envió un audio que dice: [Transcripción]. Respondé con texto breve."

Por qué suma: Mauri mandó audios para explicar su negocio. Sus clientes hacen lo mismo. Es una ventaja competitiva brutal contra otros bots básicos.

3. "CRM Ligero" (Detectar Intención de Compra)
Prioridad: BAJA (Pero alto valor) 🟢

Mauri quiere vender. A veces los chats son largos y se pierde quién quería comprar y quién solo preguntaba.

La Feature: Que Nico etiquete automáticamente la conversación en el Dashboard.

Cómo funciona:

Le pedís al LLM que, además de la respuesta, devuelva una "etiqueta de estado" en un JSON oculto.

Estados: CONSULTA, INTERESADO, LISTO_PARA_PAGAR, RECLAMO.

En el Dashboard (admin.html), mostrás la lista de chats con badges de colores:

Juan (Consultando) - Gris

Maria (Listo para Pagar) - Verde Brillante 💲

Mauri entra al panel y sabe a quién priorizar.

Por qué suma: Transforma el chat en una herramienta de ventas. Mauri ve el panel y dice: "Uhh, tengo 3 cierres pendientes", y entra a cobrar.

📝 Resumen de tus próximos To-Dos técnicos
Si yo fuera vos, atacaría en este orden:

Implementar SQLite + Evolution API (El plan que armaste antes).

To-Do Urgente: Agregar la lógica del Switch de Pausa (Handoff manual) en la base de datos y la UI. Sin esto, conectar el WhatsApp real es riesgoso.

To-Do Visual: Poner los badges de estado (channel='whatsapp') en el sidebar para diferenciar tests de realidad.