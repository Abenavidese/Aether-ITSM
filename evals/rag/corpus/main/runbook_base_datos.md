# Runbook — Base de datos Postgres de producción

## Conexiones agotadas

El error "remaining connection slots are reserved" o "too many clients
already" indica que se agotó el pool de conexiones (máximo 100). Causa más
común: un despliegue nuevo que abre conexiones sin cerrarlas. Acciones:
revisar en pg_stat_activity qué aplicación tiene más conexiones "idle in
transaction", y pedir al dueño del servicio que lo corrija. Las
aplicaciones deben conectarse por PgBouncer (puerto 6543), nunca directo
al puerto 5432.

## Réplica de lectura atrasada

Si los reportes muestran datos viejos, revisar el retraso de la réplica
(replication lag) en el panel de monitoreo. Más de 5 minutos de retraso
es una alerta SEV3. Los reportes nunca deben consultar la base primaria.

## Backups

Se hace un backup completo diario a las 03:00 (hora de Ecuador) y se
guardan 30 días. Además hay recuperación a un punto en el tiempo (PITR)
de los últimos 7 días.

## Restaurar datos borrados por error

Una restauración se pide con ticket de prioridad alta indicando tabla,
filas afectadas y hora aproximada del borrado. Se restaura en una base
temporal y se copian solo las filas necesarias; nunca se restaura encima
de producción.
