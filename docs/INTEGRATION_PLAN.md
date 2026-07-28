# Plan de integración

## Orden de carga

1. Ubicaciones: país, provincia, cantón, distrito y barrio.
2. Consulta de contribuyentes y configuración de Hacienda.
3. Tipo de cambio del BCCR.
4. Núcleo de facturación electrónica.
5. CABYS y equivalencias SAC.
6. Importación de comprobantes de proveedores.
7. Reportes QWeb.
8. Punto de Venta.
9. Automatizaciones.
10. Panel centralizado de configuración.

## Reglas

- No modificar los addons fuente.
- No declarar dependencias hacia los addons fuente.
- Mantener los nombres de modelos y campos para simplificar el traslado.
- Renombrar IDs XML duplicados antes de incluir archivos en el manifiesto.
- Cambiar referencias `env.ref()` y `ref=""` al espacio
  `l10n_cr_ticofac` cuando el registro sea trasladado.
- Conservar referencias a módulos oficiales de Odoo sin cambios.
- Validar cada capa en una base nueva antes de integrar la siguiente.

## Colisiones conocidas

- `res_config_settings_view_form`
- `view_company_form_inherit`
- `view_move_form_inherit`
- `view_res_partner_inherit`
- plantillas con identificadores genéricos

## Configuración final

Las opciones empresariales y fiscales se mostrarán en Contabilidad/Ajustes.
Las integraciones generales, diagnósticos y automatizaciones se mostrarán en
Ajustes generales bajo una sección denominada “Ticofac Costa Rica”.


## Regla de experiencia de usuario

- No crear menús superiores ni submenús técnicos para configurar el addon.
- Usar `res.config.settings` y las vistas estándar de Ajustes de Odoo.
- Mostrar la configuración fiscal en Contabilidad / Configuración / Ajustes.
- Mostrar integraciones, automatizaciones y diagnóstico en Ajustes generales, dentro de “Ticofac Costa Rica”.
- Conservar menús únicamente para operaciones sobre registros, nunca para parámetros técnicos.
- Presentar valores recomendados, ayudas claras y validación del estado de la configuración.
