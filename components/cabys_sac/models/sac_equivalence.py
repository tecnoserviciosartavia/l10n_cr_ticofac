from odoo import models, fields, api
import re


class CabysSACEquivalence(models.Model):
    _name = 'cabys.sac.equivalence'
    _description = 'Equivalencia entre SAC versión 2017 y CABYS'
    _rec_name = 'sac_code'

    sac_code = fields.Char(string='SAC versión 2017', required=True, index=True)
    sac_code_clean = fields.Char(string='SAC limpio', help='Código SAC sin separadores', index=True)
    cabys_product_id = fields.Many2one(
        comodel_name='cabys.producto',
        string='Producto Cabys',
        required=True,
        index=True,
        ondelete='restrict',
    )
    cabys_code = fields.Char(related='cabys_product_id.codigo', string='Código Cabys', store=True, readonly=True)

    _sql_constraints = [
        ('sac_unique', 'unique(sac_code)', 'Ya existe una equivalencia para este código SAC.'),
    ]

    def name_get(self):
        res = []
        for rec in self:
            label = rec.sac_code or ''
            if rec.cabys_code:
                label = f"{label} → {rec.cabys_code}"
            if rec.cabys_product_id and rec.cabys_product_id.name:
                label = f"{label} - {rec.cabys_product_id.name}"
            res.append((rec.id, label))
        return res

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = args or []
        domain = []
        if name:
            clean = re.sub(r"\D", "", name or "")
            domain = ['|', '|', ('sac_code', operator, name), ('sac_code_clean', operator, clean), ('cabys_code', operator, name)]
        recs = self.search(domain + args, limit=limit)
        return recs.name_get()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            sac = vals.get('sac_code') or ''
            vals['sac_code_clean'] = re.sub(r"\D", "", sac)
        return super().create(vals_list)

    def write(self, vals):
        if 'sac_code' in vals:
            sac = vals.get('sac_code') or ''
            vals['sac_code_clean'] = re.sub(r"\D", "", sac)
        return super().write(vals)
