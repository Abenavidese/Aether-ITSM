# Política de contraseñas y autenticación multifactor

## Requisitos de la contraseña

Las contraseñas deben tener al menos 14 caracteres. No se exigen símbolos
obligatorios, pero no pueden contener el nombre de la empresa ni el del
usuario. Se recomienda usar una frase de contraseña.

## Rotación

La contraseña de la cuenta corporativa se cambia cada 180 días, o de
inmediato si hay sospecha de que fue expuesta. No se pueden reutilizar
las últimas 5 contraseñas.

## MFA obligatorio

La autenticación multifactor es obligatoria para correo, VPN, SSO de AWS y
el ERP. El método aprobado es Microsoft Authenticator con notificación
push y número de verificación. Los SMS solo se aceptan como método de
respaldo.

## Pérdida o cambio del teléfono con MFA

Si el usuario perdió o cambió el teléfono donde tenía el autenticador, debe
llamar a la mesa de ayuda (extensión 5000) para que se verifique su
identidad con videollamada y se reinicie el registro de MFA. Por ticket o
correo no se reinicia el MFA de nadie.

## Bloqueo de cuenta

Tras 5 intentos fallidos de inicio de sesión en 10 minutos la cuenta se
bloquea durante 30 minutos. El desbloqueo antes de ese plazo lo hace la
mesa de ayuda previa verificación de identidad.
