# Open Spec: Aether ITSM

## Trazabilidad de Cambios

### Fecha: 13 de Septiembre de 2026 (Auditoría de Seguridad y Estabilidad)

Durante esta sesión se consolidó la arquitectura y se implementaron funcionalidades clave para la **Hackathon (Nebius x NVIDIA Global AI)**, junto con una refactorización crítica del sistema para el pase a producción.

## 🚀 Funcionalidades Principales Implementadas

1. **Agente IA Autónomo ("Aether") con LangGraph:**
   - Creación de un **Autonomy Cascade** (Máquina de estados): El agente evalúa el nivel de riesgo del ticket de ITSM (Risk Level 1 a 4).
   - Integración con **NVIDIA Nemotron 3** a través de **Nebius Token Factory**.
   - Soporte para **Streaming Asíncrono** en tiempo real del razonamiento del agente hacia el frontend.

2. **Integración con GitHub (Model Context Protocol - MCP):**
   - Panel de configuración para conectar repositorios.
   - Autenticación y validación asíncrona (vía `httpx`) con la API de GitHub.
   - Encriptación robusta en base de datos de los tokens de integración (usando `Fernet`).

3. **Arquitectura Multi-Tenant (B2B SaaS):**
   - Modelado de base de datos para manejar múltiples Compañías (Tenants) y Usuarios (Admins/Employees).
   - Sistema de **Onboarding Dinámico** donde las empresas configuran sus credenciales (GitHub) y su motor LLM preferido (`nemotron-nano`, etc.).
   - Soporte para planes de suscripción (Free, Pro, Enterprise).

4. **Dashboard de Administración Moderno (Vite + React + Tailwind):**
   - Interfaz con modo oscuro premium.
   - Panel de gestión de equipo (`TeamManagementPanel`) para invitar empleados.
   - Panel de perfil de usuario (`ProfilePanel`) y configuración de la empresa.
   - Flujo de revisión humana (Human-in-the-Loop): Interfaz para que los administradores aprueben acciones bloqueadas por el agente (`/approve`).

5. **API Backend Robusta (FastAPI):**
   - Webhooks asíncronos (`/api/webhook/ticket`) para recibir incidencias desde sistemas ITSM externos.
   - Base de datos local transaccional mediante `SQLite` y `SQLAlchemy`.
   - Punto de control (Checkpointer) de LangGraph integrado asíncronamente para persistir el hilo de conversación de cada ticket.

---

## 🛡️ Trazabilidad de Auditoría y Seguridad

Se resolvieron satisfactoriamente 9 incidentes reportados (5 críticos, 4 medios) para asegurar el entorno de producción:

#### 🔴 Críticos (Bloqueantes para Producción)
1. **Webhook público (`/api/webhook/ticket`) expuesto:**
   - **Problema:** No tenía autenticación, permitiendo invocar el agente de IA libremente.
   - **Solución:** Se añadió validación obligatoria con `x_api_key: str = Header(...)` validando el tenant en base de datos.
2. **`/approve` sin autenticación:**
   - **Problema:** Se podía aprobar tickets del agente con solo saber el `thread_id`.
   - **Solución:** Se integró `Depends(get_current_user)` validando el rol de administrador o superadmin antes de proceder.
3. **Password "admin123" hardcodeada:**
   - **Problema:** La contraseña inicial del superadmin estaba explícita en código.
   - **Solución:** Modificada para depender exclusivamente de `os.environ.get("SUPERADMIN_PASSWORD")` vía variables de entorno.
4. **Elevación de privilegios en el Registro:**
   - **Problema:** El formulario permitía enviar `role="superadmin"`.
   - **Solución:** El backend fue refactorizado para forzar `role="admin"` directamente en el servicio de creación (`src/auth/service.py`), ignorando cualquier inyección del cliente.
5. **JWT en localStorage (Vulnerable a XSS):**
   - **Problema:** Se guardaban tokens de autenticación en texto plano en el frontend.
   - **Solución:** Migración completa a **HttpOnly, Secure Cookies**. Se eliminó la gestión manual del token y ahora la sesión es validada automáticamente por el navegador a través del endpoint `/api/auth/me`.

#### 🟡 Medios (Estabilidad y Rendimiento)
6. **I/O bloqueante (requests síncrono):**
   - **Problema:** `requests.get()` en `src/tenant/router.py` bloqueaba el event loop.
   - **Solución:** Implementación de `httpx.AsyncClient().get()` con un endpoint 100% asíncrono.
7. **Reutilización del `JWT_SECRET_KEY` para encriptación:**
   - **Problema:** Derivaba de la llave del token para crear las llaves de los tokens de GitHub.
   - **Solución:** Se implementó una clave dedicada `ENCRYPTION_KEY` de 32 bytes (base64 url-safe), garantizando separación de responsabilidades.
8. **Rate Limiting ausente:**
   - **Problema:** Las rutas de autenticación eran susceptibles a ataques de fuerza bruta.
   - **Solución:** Integración de la biblioteca `slowapi`, asignando reglas limitantes como `@limiter.limit("5/minute")` para los endpoints de login y registro.
9. **Loop infinito en Frontend (Onboarding):**
   - **Problema:** Si el componente no refrescaba el perfil post-onboarding, la UI se congelaba.
   - **Solución:** Se integró la función `login('/admin')` al completar el asistente de configuración para refrescar la cookie asíncronamente y recargar el contexto completo.

**Estado Final:** Backend seguro, frontend adaptado a cookies de máxima privacidad y build (TypeScript/Vite) comprobado sin errores de compilación.
