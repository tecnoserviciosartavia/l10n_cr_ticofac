from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CabysSacConfigWizard(models.TransientModel):
    _name = 'cabys.sac.config.wizard'
    _description = 'Configuración: Búsqueda por Equivalencia SAC → CABYS'

    enable_cabys_sac_search = fields.Boolean(
        string='Habilitar búsqueda por equivalencia SAC → CABYS',
        help='Si está activo, los productos mostrarán un campo para seleccionar el CABYS a partir de un código SAC 2017.'
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        icp = self.env['ir.config_parameter'].sudo()
        val = icp.get_param('l10n_cr_ticofac.enable_cabys_sac_search', default='0')
        res['enable_cabys_sac_search'] = True if str(val).lower() in ('1', 'true', 'yes') else False
        return res

    def action_save(self):
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('l10n_cr_ticofac.enable_cabys_sac_search', '1' if self.enable_cabys_sac_search else '0')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Configuración guardada'),
                'message': _('La configuración de búsqueda por equivalencia SAC → CABYS ha sido actualizada.'),
                'sticky': False,
            }
        }
