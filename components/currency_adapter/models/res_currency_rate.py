from odoo import api, fields, models, _
from odoo.exceptions import UserError
from zeep import Client
from datetime import timedelta, datetime
import xml.etree.ElementTree
import logging
import requests
from lxml import etree

_logger = logging.getLogger(__name__)


class ResCurrencyRate(models.Model):
    _inherit = 'res.currency.rate'

    rate = fields.Float(digits='Currency Rate Precision')

    # === Deprecated === #
    # Now Odoo has the company_rate and inverse_company_rate
    original_rate = fields.Float(
        string='Selling Rate in Costa Rica',
        digits=0,
        aggregator="avg",
        help='The selling exchange rate from CRC to USD as it is send from BCCR')

    # ==============================================================================================
    #                                          Currency Rate - Buy
    # ==============================================================================================

    rate_2 = fields.Float(
        digits='Currency Rate Precision',
        aggregator="avg",
        help='The buying rate of the currency to the currency of rate 1.')

    original_rate_2 = fields.Float(
        digits=0,
        compute="_compute_original_rate_2",
        inverse="_inverse_original_rate_2",
        aggregator="avg",
        help='The buying exchange rate from CRC to USD as it is send from BCCR')

    inverse_original_rate_2 = fields.Float(
        digits=0,
        string='Technical Rate - Buy',
        compute="_compute_inverse_original_rate_2",
        inverse="_inverse_inverse_original_rate_2",
        aggregator="avg",
        help="The rate of the currency to the currency of rate 1 ",
    )

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def _get_latest_rate_2(self):
        # Make sure 'name' is defined when creating a new rate.
        if not self.name:
            raise UserError(_("The date for the current rate is empty.\nPlease set it."))
        return self.currency_id.rate_ids.sudo().filtered(lambda x: (
            x.rate_2
            and x.company_id == (self.company_id or self.env.company)
            and x.name < (self.name or fields.Date.today())
        )).sorted('name')[-1:]

    def _get_last_rates_for_companies_2(self, companies):
        return {
            company: company.currency_id.rate_ids.sudo().filtered(lambda x: (
                x.rate_2
                and x.company_id == company or not x.company_id
            )).sorted('name')[-1:].rate_2 or 1
            for company in companies
        }

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('rate_2', 'name', 'currency_id', 'company_id', 'currency_id.rate_ids.rate_2')
    @api.depends_context('company')
    def _compute_original_rate_2(self):
        last_rate = self.env['res.currency.rate']._get_last_rates_for_companies_2(self.company_id | self.env.company)
        for currency_rate in self:
            company = currency_rate.company_id or self.env.company
            currency_rate.original_rate_2 = (currency_rate.rate_2 or self._get_latest_rate_2().rate_2 or 1.0) / last_rate[company]

    @api.depends('original_rate_2')
    def _compute_inverse_original_rate_2(self):
        for currency_rate in self:
            currency_rate.inverse_original_rate_2 = 1.0 / currency_rate.original_rate_2

    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------

    @api.onchange('original_rate_2')
    def _inverse_original_rate_2(self):
        last_rate = self.env['res.currency.rate']._get_last_rates_for_companies_2(self.company_id | self.env.company)
        for currency_rate in self:
            company = currency_rate.company_id or self.env.company
            currency_rate.rate_2 = currency_rate.original_rate_2 * last_rate[company]

    @api.onchange('inverse_original_rate_2')
    def _inverse_inverse_original_rate_2(self):
        for currency_rate in self:
            currency_rate.original_rate_2 = 1.0 / currency_rate.inverse_original_rate_2

    @api.onchange('original_rate_2')
    def _onchange_rate_2_warning(self):
        latest_rate = self._get_latest_rate_2()
        if latest_rate:
            diff = (latest_rate.rate_2 - self.rate_2) / latest_rate.rate_2
            if abs(diff) > 0.2:
                return {
                    'warning': {
                        'title': _("Warning for %s", self.currency_id.name),
                        'message': _(
                            "The new rate is quite far from the previous rate.\n"
                            "Incorrect currency rates may cause critical problems, make sure the rate is correct !"
                        )
                    }
                }

    # -------------------------------------------------------------------------
    # CRON
    # -------------------------------------------------------------------------

    @api.model
    def _cron_update(self, first_date=False, last_date=False):
        _logger.info("=========================================================")
        _logger.info("Executing exchange rate update")

        # Usar el contexto de la compañía principal para todas las operaciones de tasas de cambio
        main_company = self.env['res.company']._get_main_company()
        currency_rate_obj = self.env['res.currency.rate'].with_company(main_company)

        exchange_source = self.env['ir.config_parameter'].sudo().get_param('exchange_source')
        usd_currency = self.env.ref('base.USD')
        
        if not usd_currency:
            _logger.error("Error: La moneda USD (Dólares Americanos) no se encontró.")
            return

        if exchange_source == 'bccr':
            _logger.info("Getting exchange rates from BCCR")
            bccr_username = self.env['ir.config_parameter'].sudo().get_param('bccr_username')
            bccr_email = self.env['ir.config_parameter'].sudo().get_param('bccr_email')
            bccr_token = self.env['ir.config_parameter'].sudo().get_param('bccr_token')

            if first_date:
                initial_date_str = first_date.strftime('%d/%m/%Y')
                end_date_str = last_date.strftime('%d/%m/%Y')
            else:
                initial_date_str = datetime.now().date().strftime('%d/%m/%Y')
                end_date_str = initial_date_str

            try:
                client = Client('https://gee.bccr.fi.cr/Indicadores/Suscripciones/WS/wsindicadoreseconomicos.asmx?WSDL')
                
                # Obtener la tasa de venta (318)
                response_venta = client.service.ObtenerIndicadoresEconomicosXML(
                    Indicador='318', FechaInicio=initial_date_str, FechaFinal=end_date_str,
                    Nombre=bccr_username, SubNiveles='N', CorreoElectronico=bccr_email, Token=bccr_token)
                xml_response_venta = xml.etree.ElementTree.fromstring(response_venta)
                selling_rate_nodes = xml_response_venta.findall("./INGC011_CAT_INDICADORECONOMIC")
                
                # Obtener la tasa de compra (317)
                response_compra = client.service.ObtenerIndicadoresEconomicosXML(
                    Indicador='317', FechaInicio=initial_date_str, FechaFinal=end_date_str,
                    Nombre=bccr_username, SubNiveles='N', CorreoElectronico=bccr_email, Token=bccr_token)
                xml_response_compra = xml.etree.ElementTree.fromstring(response_compra)
                buying_rate_nodes = xml_response_compra.findall("./INGC011_CAT_INDICADORECONOMIC")

            except Exception as e:
                _logger.error("Error connecting to BCCR API: %s", e)
                return False

            if len(selling_rate_nodes) > 0 and len(selling_rate_nodes) == len(buying_rate_nodes):
                for node_venta, node_compra in zip(selling_rate_nodes, buying_rate_nodes):
                    if node_venta.find("DES_FECHA").text == node_compra.find("DES_FECHA").text:
                        current_date_str = datetime.strptime(node_venta.find("DES_FECHA").text,
                                                             "%Y-%m-%dT%H:%M:%S-06:00").strftime('%Y-%m-%d')
                        
                        selling_original_rate = float(node_venta.find("NUM_VALOR").text)
                        buying_original_rate = float(node_compra.find("NUM_VALOR").text)

                        # Odoo usa el valor inverso
                        selling_rate = 1 / selling_original_rate
                        buying_rate = 1 / buying_original_rate

                        # Buscar la tasa de cambio con el contexto de la compañía principal
                        rates_ids = currency_rate_obj.search([
                            ('name', '=', current_date_str),
                            ('currency_id', '=', usd_currency.id),
                        ], limit=1)

                        vals = {
                            'rate': selling_rate,
                            'inverse_company_rate': selling_original_rate,
                            'original_rate': selling_original_rate,
                            'rate_2': buying_rate,
                            'original_rate_2': buying_original_rate,
                            'currency_id': usd_currency.id,
                            'company_id': main_company.id, 
                        }

                        if rates_ids:
                            # Actualizar el registro existente
                            rates_ids.write(vals)
                        else:
                            # Crear el nuevo registro usando el objeto con el contexto correcto
                            vals['name'] = current_date_str
                            currency_rate_obj.create(vals)

                    else:
                        _logger.error("Error loading currency rates, dates for a buying and selling rates don't match")
            else:
                _logger.error("Error loading currency rates, data for buying and selling rates don't match")

        elif exchange_source == 'hacienda':
            _logger.info("Getting exchange rates from HACIENDA")
            
            initial_date = first_date if first_date else datetime.now().date()
            end_date = last_date if last_date else initial_date

            try:
                url = 'https://api.hacienda.go.cr/indicadores/tc/dolar/historico/?d='+initial_date.strftime('%Y-%m-%d')+'&h='+end_date.strftime('%Y-%m-%d')
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as e:
                _logger.error('RequestException %s', e)
                return False

            if response.status_code in (200,):
                if isinstance(data, list):
                    for rate_line in data:
                        today = datetime.strptime(rate_line['fecha'], '%Y-%m-%d %H:%M:%S')
                        
                        rates_ids = currency_rate_obj.search([('name', '=', today.date()),
                                                            ('currency_id', '=', usd_currency.id),
                                                            ], limit=1)
                        
                        vals = {
                            'original_rate': rate_line['venta'],
                            'inverse_company_rate': rate_line['venta'],
                            'rate': 1 / rate_line['venta'],
                            'original_rate_2': rate_line['compra'],
                            'rate_2': 1 / rate_line['compra'],
                            'currency_id': usd_currency.id,
                            'company_id': main_company.id,
                        }
                        
                        if rates_ids:
                            rates_ids.write(vals)
                        else:
                            vals['name'] = today.date()
                            currency_rate_obj.create(vals)
                else:
                    _logger.error("Hacienda API returned an unexpected data format.")
                    
        _logger.info("=========================================================")

    def _create_the_latest_exchange_rate_to_date(self, currency, date=None):
        name = date or datetime.now()
        companies = self.env['res.company'].search([])
        for company in companies:
            currency_rate_obj = self.env['res.currency.rate'].search([
                ('company_id', '=', company.id),
                ('currency_id', '=', currency.id),
                ('name', '<=', name),
            ], limit=1, order='name desc')

            if currency_rate_obj.name == name:
                return

            self.create({
                'name': name,
                'rate': currency_rate_obj.rate,
                'inverse_company_rate': currency_rate_obj.inverse_company_rate,
                'original_rate': currency_rate_obj.original_rate,
                'rate_2': currency_rate_obj.rate_2,
                'original_rate_2': currency_rate_obj.original_rate_2,
                'currency_id': currency_rate_obj.currency_id.id,
                'company_id': company.id,
            })

    # -------------------------------------------------------------------------
    # TOOLING
    # -------------------------------------------------------------------------

    @api.model
    def _fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        result = super()._fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type in ('tree'):
            names = {
                'company_currency_name': (self.env['res.company'].browse(self._context.get('company_id')) or self.env.company).currency_id.name,
                'rate_currency_name': self.env['res.currency'].browse(self._context.get('active_id')).name or 'Unit',
            }
            doc = etree.XML(result['arch'])
            for field in [['original_rate_2', _('%(company_currency_name)s per %(rate_currency_name)s - Buy', **names)],
                          ['inverse_original_rate_2', _('%(rate_currency_name)s per %(company_currency_name)s - Buy', **names)],
                          ]:
                node = doc.xpath("//tree//field[@name='%s']" % field[0])
                if node:
                    node[0].set('string', field[1])
            result['arch'] = etree.tostring(doc, encoding='unicode')
        return result