# Beneficios aliados: despliegue y operacion

Clientes con una compra aprobada en el mes (hora de Colombia) ven los codigos de
descuento de los negocios aliados. Codigo y logica: `products/alianzas.py`.
Esquema: `products/sql/2026-10-alianzas.sql`. Front: `frontend-v2`
`src/components/AlliesBenefits.tsx`, dentro de `/beneficios`.

## Regla del codigo (la que se le explica a cada aliado)
`PRIMERA LETRA + ULTIMA LETRA del nombre del negocio` + `-` + ultimos 4 digitos de
`SECRETO x NUMERO DEL MES` (enero = 1 ... diciembre = 12), con ceros a la izquierda.
Ej.: Deportes, secreto 417, octubre -> 417 x 10 = 4170 -> `DS-4170`.
El secreto es de 3 digitos, distinto por aliado, y solo lo conocen el aliado y HG.
Si un aliado tiene `codigo_fijo`, ese reemplaza al automatico.

## Orden de despliegue (mismo criterio que cuotas-y-reserva, §8)
1. **SQL** en `hc-postgres` (idempotente, solo crea tablas nuevas):
   ```bash
   docker exec -i hc-postgres psql -U hardcoregames -d hardcoregames -v ON_ERROR_STOP=1 \
     < /opt/hardcoregames/repos/django/products/sql/2026-10-alianzas.sql
   ```
2. **Django** (`hc-django`) con el commit que incluye `products/alianzas.py`. FastAPI no cambia.
3. **frontend-v2** (`hc-frontend-v2`).
4. **Aliados**: crearlos en el admin de Django (Products > Aliados). Elige un secreto
   de 3 dígitos por aliado (100-999), no consecutivos ni repetidos. Para generarlos:
   ```bash
   python -c "import secrets; print(100 + secrets.randbelow(900))"
   ```
5. **Probar cerrado**: `ALIANZAS_ABIERTO` sin definir -> solo superusuarios ven la
   seccion en `/beneficios`. Entra con tu cuenta, revisa que el codigo coincida con
   la regla de arriba (el admin muestra la columna "Codigo este mes").
6. **Abrir**: agregar `ALIANZAS_ABIERTO=1` a `/root/hc/hc-django.env` y reiniciar
   `hc-django`. Desde ese momento todos ven la seccion y el correo de compra incluye el aviso.

## Rollback
`bash /root/deploy_hc.sh <servicio> rollback`. Las tablas nuevas quedan sin uso y no
estorban. Para cerrar sin desplegar: quitar `ALIANZAS_ABIERTO` y reiniciar `hc-django`.

## Metricas
Aperturas por aliado y mes:
```sql
SELECT a.nombre, o.mes, count(*) AS aperturas, count(DISTINCT o.user_id) AS clientes
FROM products_aliadoapertura o JOIN products_aliado a ON a.id = o.aliado_id
GROUP BY a.nombre, o.mes ORDER BY o.mes DESC, a.nombre;
```

## Pendiente conocido
- El correo de **reserva** (`enviar_correo_reserva_confirmada`) aun no lleva el aviso.
- El codigo se repite cada año (secreto x mes, sin año): si un aliado lo filtra, cambia su secreto.
