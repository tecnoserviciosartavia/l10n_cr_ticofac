from odoo import models, fields


class ResCompanyCabysSac(models.Model):
    _inherit = 'res.company'

    enable_cabys_sac_search = fields.Boolean(
        string='Habilitar búsqueda por equivalencia SAC → CABYS',
        help='Si está activo, los productos mostrarán un campo para seleccionar el CABYS a partir de un código SAC 2017.',
        default=False,
    )
