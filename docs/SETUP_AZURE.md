# Alta de la app en Azure AD / Entra ID

Esta guía es para que el servicio pueda **leer mails y descargar adjuntos** del
buzón TTFA sin usar la contraseña de un usuario. Se hace una sola vez.

## 0. Prerrequisitos

- Cuenta de **administrador** del tenant de Microsoft 365 de TTFA (sin admin
  no se puede dar consentimiento ni aplicar policies).
- Saber qué buzón se va a leer (ej. `tpozo@ttfasa.com`).

## 1. Registrar la aplicación

1. Entrá a [https://entra.microsoft.com](https://entra.microsoft.com) → **Identity → Applications → App registrations → New registration**.
2. Datos:
   - **Name**: `ttfa-kpi-ingest`
   - **Supported account types**: *Accounts in this organizational directory only* (single tenant).
   - **Redirect URI**: vacío (no aplica para app-only).
3. *Register*.
4. En la pantalla *Overview*, anotá:
   - **Application (client) ID** → `MS_CLIENT_ID`
   - **Directory (tenant) ID** → `MS_TENANT_ID`

## 2. Crear un client secret

1. Dentro del registro, **Certificates & secrets → Client secrets → New client secret**.
2. Description: `ttfa-kpi-ingest-secret`. Expiration: 12 o 24 meses (anotá la
   fecha para rotarlo a tiempo).
3. Copiá el valor de la columna **Value** (NO la columna *Secret ID*). Solo se
   muestra una vez. → `MS_CLIENT_SECRET`.

## 3. Conceder permisos de Graph

1. **API permissions → Add a permission → Microsoft Graph → Application
   permissions** (NO *Delegated*).
2. Agregar:
   - `Mail.Read` — siempre, es el mínimo.
   - `Mail.ReadWrite` — solo si vas a usar `MARK_AS_READ=true`.
3. Volver a *API permissions* y clickear **Grant admin consent for <Tenant>**.
   Debe quedar el ✅ verde junto a cada permiso.

> ⚠️ *Application permissions* da acceso a **todos los buzones del tenant** por
> default. El paso 5 (Application Access Policy) restringe ese alcance a un
> solo buzón.

## 4. Configurar el .env

Pegar los valores en `.env`:

```
MS_TENANT_ID=<Directory (tenant) ID>
MS_CLIENT_ID=<Application (client) ID>
MS_CLIENT_SECRET=<el valor del secret>
MS_MAILBOX=tpozo@ttfasa.com
```

Probar localmente:

```bash
docker compose run --rm -e RUN_MODE=once ingest
```

Esperado en logs: "Arrancando ingesta..." sin errores de auth.

## 5. (Recomendado) Restringir a un solo buzón

Sin esta policy, la app podría leer cualquier buzón del tenant. La policy
limita el acceso al buzón indicado.

```powershell
# Conectar a Exchange Online (PowerShell). Una sola vez:
Install-Module -Name ExchangeOnlineManagement -Scope CurrentUser
Connect-ExchangeOnline -UserPrincipalName admin@ttfasa.com

# Crear un mail-enabled security group con el buzón permitido:
New-DistributionGroup -Name "TTFA-KPI-Ingest-Allowed" -Type "Security" -Members tpozo@ttfasa.com

# Aplicar la policy a la app (usar el Application (client) ID):
New-ApplicationAccessPolicy `
  -AppId <MS_CLIENT_ID> `
  -PolicyScopeGroupId TTFA-KPI-Ingest-Allowed@ttfasa.com `
  -AccessRight RestrictAccess `
  -Description "Limitar ttfa-kpi-ingest al buzón de KPI"

# Verificar que efectivamente está restringida:
Test-ApplicationAccessPolicy -Identity tpozo@ttfasa.com -AppId <MS_CLIENT_ID>
# → AccessCheckResult debe decir "Granted".

Test-ApplicationAccessPolicy -Identity otra-persona@ttfasa.com -AppId <MS_CLIENT_ID>
# → AccessCheckResult debe decir "Denied".
```

La policy puede tardar **30-60 minutos** en propagarse.

## 6. Rotación del secret

Antes de la fecha de expiración:

1. Volver a **Certificates & secrets → New client secret**.
2. Actualizar `MS_CLIENT_SECRET` en el `.env` del VPS y reiniciar el contenedor.
3. Una vez verificado que funciona, **eliminar el secret viejo**.

## Errores comunes

| Síntoma                                              | Causa probable                                  | Fix |
|------------------------------------------------------|-------------------------------------------------|-----|
| `AADSTS7000215: Invalid client secret`               | secret mal copiado o vencido                    | Generar uno nuevo. |
| `Authorization_RequestDenied` al leer mails          | falta admin consent o permiso es *Delegated*    | Volver al paso 3, usar *Application*. |
| `ErrorAccessDenied` específicamente sobre el buzón   | Application Access Policy aplicada con grupo equivocado | Revisar `Test-ApplicationAccessPolicy`. |
| Token OK pero `find_messages` devuelve 0             | LOOKBACK_DAYS chico o prefijo de asunto cambió  | Subir LOOKBACK_DAYS, revisar `CHILE_SUBJECT_PREFIX` / `BRASIL_SUBJECT_PREFIX`. |
