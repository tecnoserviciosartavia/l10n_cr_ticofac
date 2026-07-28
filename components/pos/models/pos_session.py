# -*- coding: utf-8 -*-
# Module develop by @jartavia05

from odoo import api, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_res_company(self):
        result = super()._loader_params_res_company()
        result['search_params']['fields'].append('invoice_is_electronic')
        return result

    @api.model
    def _load_pos_data_models(self, config_id):
        """Add discount.code to models loaded in POS"""
        data = super()._load_pos_data_models(config_id)
        if "discount.code" not in data:
            data.append("discount.code")
        if "reference.code" not in data:
            data.append("reference.code")
        return data

    def _loader_params_reference_code(self):
        return {
            "search_params": {
                "domain": [("active", "=", True)],
                "fields": ["name", "code", "active"],
            },
        }

    def _get_pos_ui_reference_code(self, params):
        return self.env["reference.code"].search_read(**params["search_params"])

    def _loader_params_discount_code(self):
        return {
            "search_params": {
                "domain": [("active", "=", True)],
                "fields": ["name", "code", "rate", "active"],
            },
        }

    def _get_pos_ui_discount_code(self, params):
        return self.env["discount.code"].search_read(**params["search_params"])
