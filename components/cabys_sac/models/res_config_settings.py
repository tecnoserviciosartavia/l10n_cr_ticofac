from odoo import models, fields


class ResConfigSettingsCabysSac(models.TransientModel):
    _inherit = 'res.config.settings'

    enable_cabys_sac_search = fields.Boolean(
        string='Habilitar búsqueda por equivalencia SAC → CABYS',
        help='Si está activo, los productos mostrarán un campo para seleccionar el CABYS a partir de un código SAC 2017.',
        config_parameter='l10n_cr_ticofac.enable_cabys_sac_search',
    )
