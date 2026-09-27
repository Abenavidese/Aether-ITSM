# Guía de despliegue del frontend (Vercel)

## Cómo se despliega

El frontend (React + Vite) se despliega en Vercel. Cada push a la rama main
genera un despliegue de producción; cada pull request genera un
despliegue de vista previa (preview) con su propia URL.

## Variables de entorno

Las variables que usa el navegador deben empezar con VITE_ (por ejemplo
VITE_API_URL, que apunta al backend en Render). Una variable sin ese
prefijo no llega al código del navegador y queda como undefined. Cambiar
una variable en Vercel no afecta al despliegue actual: hay que volver a
desplegar.

## Volver a una versión anterior (rollback)

En Vercel > Deployments se elige el último despliegue sano y se usa
"Promote to Production". El rollback es inmediato y no requiere un nuevo
build. Avisar en el canal de despliegues qué versión se promovió.

## Error "Build exceeded maximum duration"

Este error aparece cuando el build supera 45 minutos. Suele deberse a que
se instalaron dependencias sin la caché (lockfile modificado) o a un script
postinstall lento. Revisar que package-lock.json esté commiteado y quitar
scripts innecesarios.
