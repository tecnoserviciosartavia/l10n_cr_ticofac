# l10n_cr_ticofac

Localización unificada de Costa Rica para Ticofac.

## Objetivo

Ofrecer una sola aplicación de Odoo para:

- facturación electrónica de Costa Rica;
- catálogo CABYS y equivalencias SAC;
- ubicación administrativa costarricense;
- consulta de contribuyentes en Hacienda;
- tipo de cambio del BCCR;
- importación de facturas de proveedores;
- representación gráfica QWeb;
- facturación electrónica desde Punto de Venta;
- automatizaciones y configuración centralizada.

La configuración administrativa se realizará desde los Ajustes estándar de Odoo. El addon no utilizará menús superiores adicionales para parámetros técnicos.

## Estado

El addon se encuentra en integración. Permanece con `installable=False` para
evitar instalaciones incompletas mientras se trasladan y validan los
componentes.

Los módulos fuente no se modifican. El código incorporado debe conservar las
atribuciones y la licencia AGPL-3 correspondientes.

## Componentes fuente

1. `l10n_cr_country_codes`
2. `l10n_cr_hacienda_info_query`
3. `res_currency_cr_adapter`
4. `cr_electronic_invoice`
5. `add_fields_diaries`
6. `cabys`
7. `cabys_sac_equivalence`
8. `cr_import_vendor_bills`
9. `cr_electronic_invoice_qweb_fe`
10. `cr_electronic_invoice_pos`
11. `partner_economic_activities_cron`

`cr_electronic_invoice_install` no se trasladará como instalador: su función
será reemplazada por este addon único.

## Política de identificadores

Todos los nuevos identificadores XML pertenecen al espacio
`l10n_cr_ticofac`. Los identificadores duplicados de los módulos fuente deben
recibir un prefijo por componente antes de cargarse.

