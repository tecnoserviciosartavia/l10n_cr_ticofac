
from odoo import api, fields, models
from zeep import Client
from datetime import timedelta, datetime
import xml.etree.ElementTree
import logging
import requests

_logger = logging.getLogger(__name__)


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    rate = fields.Float(digits='Currency Rate Precision')

    # -------------------------------------------------------------------------
    # CRON
    # -------------------------------------------------------------------------

    def _cron_create_missing_exchange_rates(self):
        # Obtener el registro de la compañía principal
        main_company = self.env['res.company']._get_main_company()
        # Iterar sobre las monedas, pero ejecutar la acción con el contexto de la compañía principal
        for currency in self.env['res.currency'].search([('id', '!=', main_company.currency_id.id)]):
            currency.with_company(main_company).action_create_missing_exchange_rates()

    # -------------------------------------------------------------------------
    # PUBLIC ACTIONS
    # -------------------------------------------------------------------------

    def action_create_missing_exchange_rates(self):
        # La compañía principal de la instancia, no la del usuario
        main_company = self.env['res.company']._get_main_company()
        
        # Usamos with_company() para cambiar el contexto temporalmente.
        currency_rate_obj = self.env['res.currency.rate'].with_company(main_company)
        
        # A day is added to fix the loss of the current day
        today = datetime.today().date()
        last_day = today + timedelta(days=1)

        first_day = currency_rate_obj.search([
            ('company_id', '=', main_company.id),
            ('currency_id', '=', self.id)
        ], limit=1, order='name asc')
        
        if not first_day:
            if self.id == self.env.ref('base.USD').id:
                # La llamada a _cron_update también debe ser con el contexto de la compañía principal
                self.env['res.currency.rate'].with_company(main_company)._cron_update()
        else:
            range_day = last_day - first_day.name
            date = first_day.name
            for day in range(range_day.days):
                if self.id == self.env.ref('base.USD').id:
                    if not currency_rate_obj.search([('name', '=', date)], limit=1):
                        self.env['res.currency.rate'].with_company(main_company)._cron_update(date, date)
                    if not currency_rate_obj.search([('name', '=', date)], limit=1):
                        self.env['res.currency.rate'].with_company(main_company)._create_the_latest_exchange_rate_to_date(self, date)
                date += timedelta(days=1)