# Runbook — payments-api

## Arquitectura del servicio

payments-api es un servicio Node/Express desplegado en Render (servicio
srv-payments). Recibe los cobros del checkout, los envía a la pasarela
del Banco del Pacífico y guarda el resultado en la tabla payments de
Postgres. Depende de Redis para la idempotencia de los cobros.

## Error PAY-4012

PAY-4012 significa que la pasarela no respondió dentro de los 8 segundos
configurados (timeout). El cobro queda en estado "pending_confirmation" y
un job de conciliación lo confirma o lo anula a los 15 minutos. El cliente
NO debe reintentar el pago: si reintenta, el sistema lo bloquea por la
clave de idempotencia. Si hay más de 20 PAY-4012 en 5 minutos, es una
caída de la pasarela: avisar al banco por el canal de soporte comercial.

## Error PAY-2001

PAY-2001 es "tarjeta rechazada por el emisor". No es una falla del sistema;
el cliente debe usar otra tarjeta o comunicarse con su banco. No se abre
incidente por este código.

## Rotación de credenciales de la pasarela

Las credenciales de la pasarela vencen cada 90 días. Se rotan desde el
panel del banco y se actualiza la variable PAYGATE_API_SECRET en Render;
el servicio lee la nueva clave en el siguiente despliegue. Durante la
rotación ambas claves son válidas por 24 horas.

## Dónde mirar los logs

Los logs de payments-api están en Render (pestaña Logs del servicio) y se
retienen 7 días. Cada cobro registra un correlation_id que también aparece
en el panel del banco, lo que permite seguir una transacción de punta a
punta.
