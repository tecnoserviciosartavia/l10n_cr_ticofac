from odoo import api, models


class ReferenceCodePOS(models.Model):
    """Extend reference.code to load in POS"""

    _inherit = ["reference.code", "pos.load.mixin"]
    _name = "reference.code"

    @api.model
    def _load_pos_data_domain(self, data):
        """Domain to filter which reference codes load into POS"""
        return [("active", "=", True)]

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Fields to load into POS frontend"""
        return ["id", "code", "name", "active"]
