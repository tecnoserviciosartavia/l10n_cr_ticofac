import re
import json
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import phonenumbers
import logging
from datetime import datetime, timedelta, date
from . import api_facturae

_logger = logging.getLogger(__name__)


class PartnerElectronic(models.Model):
    _description = 'PartnerElectronic'
    _inherit = "res.partner"

    # ==============================================================================================
    #                                          PARTNER
    # ==============================================================================================

    # === Partner fields === #

    commercial_name = fields.Char()
    identification_id = fields.Many2one(
        comodel_name="identification.type"
    )
    payment_methods_id = fields.Many2one(
        comodel_name="payment.methods",
        string="Método de pago"
    )
    export = fields.Boolean(
        string="Es exportación",
        default=False
    )
    inscribed = fields.Boolean(
        string="Inscrito en Hacienda",
        readonly=True,
        store=True
    )

    # === Economic Activity fields === #

    activity_id = fields.Many2one(
        comodel_name="economic.activity",
        string="Actividad económica predeterminada",
        context={
            'active_test': False
        }
    )
    economic_activities_ids = fields.Many2many(
        comodel_name='economic.activity',
        string='Actividades económicas',
        context={
            'active_test': False
        }
    )

    # === Exonerations fields === #

    has_exoneration = fields.Boolean(
        string="¿Posee exoneración?",
        required=False
    )
    type_exoneration = fields.Many2one(
        comodel_name="aut.ex",
        string="Tipo de autorización"
    )
    exoneration_number = fields.Char()
    percentage_exoneration = fields.Float(
        string="Porcentaje de exoneración del IVA",
        required=False
    )
    institution_name = fields.Char(
        string="Institución emisora"
    )
    date_issue = fields.Date(
        string="Fecha de emisión"
    )
    date_expiration = fields.Date(
        string="Fecha de vencimiento"
    )
    date_notification = fields.Date(
        string="Última fecha de notificación"
    )
    allowed_cabys_ids = fields.One2many(
        comodel_name='res.partner.cabys.line',
        inverse_name='parent_id',
        string='Códigos CABYS autorizados'
    )

    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------

    @api.onchange('phone')
    def _onchange_phone(self):
        if self.phone:
            phone = phonenumbers.parse(self.phone, self.country_id and self.country_id.code or 'CR')
            valid = phonenumbers.is_valid_number(phone)
            if not valid:
                alert = {
                    'title': 'Atención',
                    'message': _('Número de teléfono inválido')
                }
                return {'value': {'phone': ''}, 'warning': alert}

    @api.onchange('mobile')
    def _onchange_mobile(self):
        if self.mobile:
            mobile = phonenumbers.parse(self.mobile, self.country_id and self.country_id.code or 'CR')
            valid = phonenumbers.is_valid_number(mobile)
            if not valid:
                alert = {
                    'title': 'Atención',
                    'message': 'Número de teléfono inválido'
                }
                return {'value': {'mobile': ''}, 'warning': alert}

    @api.onchange('email')
    def _onchange_email(self):
        if self.email:
            if not re.match(r'^(\s?[^\s,]+@[^\s,]+\.[^\s,]+\s?,)*(\s?[^\s,]+@[^\s,]+\.[^\s,]+)$', self.email.lower()):
                vals = {'email': False}
                alerta = {
                    'title': 'Atención',
                    'message': 'El correo electrónico no cumple con una estructura válida. ' + str(self.email)
                }
                return {'value': vals, 'warning': alerta}

    @api.onchange('vat')
    def _onchange_vat(self):
        if self.identification_id and self.vat:
            if self.identification_id.code == '05':
                if len(self.vat) == 0 or len(self.vat) > 20:
                    raise UserError(_('La identificación debe tener menos de 20 carateres.'))
            else:
                # Remove leters, dashes, dots or any other special character.
                self.vat = re.sub(r"[^0-9]+", "", self.vat)
                if self.identification_id.code == '01':
                    if self.vat.isdigit() and len(self.vat) != 9:
                        raise UserError(_('La identificación tipo Cédula física debe ' +
                                        'de contener 9 dígitos, sin cero al inicio y sin guiones.'))
                elif self.identification_id.code == '02':
                    if self.vat.isdigit() and len(self.vat) != 10:
                        raise UserError(_('La identificación tipo Cédula jurídica debe contener 10 ' +
                                          'dígitos, sin cero al inicio y sin guiones.'))
                elif self.identification_id.code == '03' and self.vat.isdigit():
                    if self.vat.isdigit() and len(self.vat) < 11 or len(self.vat) > 12:
                        raise UserError(_('La identificación tipo DIMEX debe contener 11 o 12 ' +
                                          'dígitos, sin ceros al inicio y sin guiones.'))
                elif self.identification_id.code == '04' and self.vat.isdigit():
                    if self.vat.isdigit() and len(self.vat) != 9:
                        raise UserError(_('La identificación tipo NITE debe contener 10 dígitos, ' +
                                          'sin ceros al inicio y sin guiones.'))

    @api.onchange('exoneration_number')
    def _onchange_exoneration_number(self):
        if self.exoneration_number:
            self.definir_informacion_exo(self.exoneration_number)
    
    @api.onchange('zip')
    def _onchange_zip_custom(self):
        for record in self:
            zip_code  = record.zip
            if zip_code and not (record.state_id or record.county_id or record.district_id or record.neighborhood_id):
                state = zip_code[:1]
                county = zip_code[1:3]
                district = zip_code[3:5]
                
                state_id = self.env['res.country.state'].search([('code', '=', state)], limit=1)

                record.state_id = state_id.id
    # -------------------------------------------------------------------------
    # TOOLING
    # -------------------------------------------------------------------------
    def action_get_economic_activities(self):
        if not self.vat:
            return {
                'value': {'vat': ''},
                'warning': {
                    'title': 'Atención',
                    'message': _('Company VAT is invalid')
                }
            }

        json_response = api_facturae.get_economic_activities(self)
        _logger.debug('E-INV CR - Economic Activities: %s', json_response)

        status = str(json_response.get("status", "")).strip()
        if status != "200":
            alert = {
                'title': status,
                'message': json_response.get("text") or json_response.get("message") or "Error desconocido"
            }
            return {'value': {'vat': ''}, 'warning': alert}

        # Obtener lista de actividades (tolerando distintos nombres)
        activities = json_response.get("activities") or json_response.get("actividades") or []
        activities_code = []
        old_activities_code = []
        for act in activities:
            estado = act.get("estado") or act.get("status")
            if str(estado).upper().startswith("A"):  # A o Activo
                code = act.get("codigo") or act.get("code")
                old_code = act.get("ciiu3", [{}])[0].get("codigo")
                if code:
                    activities_code.append(str(code).strip())
                    old_activities_code.append(str(old_code).strip())


        # Buscar las actividades en Odoo
        economic_activities = self.env['economic.activity'].with_context(active_test=False).search([
            ('code', 'in', activities_code),
            ('code_old', 'in', old_activities_code),
        ])
        self.economic_activities_ids = [(6, 0, economic_activities.ids)]
        self.activity_id = economic_activities[:1].id if economic_activities else False

        # Actualizar datos del partner
        self.name = json_response.get("name") or self.name
        situacion = (json_response.get("situacion", "") or "").strip()
        # Guardar el estado "inscribed" tanto en registros nuevos como existentes.
        # La asignación directa funciona mejor que self.write() en este flujo.
        self.inscribed = situacion in ("Inscrito", "Inscrito de Oficio")
        return True

    def definir_informacion_exo(self, cedula):
        url_base = self.sudo().env.company.url_base_exo
        if url_base:
            url_base = url_base.strip()

            if url_base[-1:] == '/':
                url_base = url_base[:-1]

            end_point = url_base + 'autorizacion=' + cedula

            headers = {
                'content-type': 'application/json',
            }

            peticion = requests.get(end_point, headers=headers, timeout=10)

            ultimo_mensaje = 'Fecha/Hora: ' + str(datetime.now()) + ', Codigo: ' + str(
                peticion.status_code) + ', Mensaje: ' + str(peticion._content.decode())

            if peticion.status_code in (200, 202) and len(peticion._content) > 0:
                contenido = json.loads(str(peticion._content, 'utf-8'))

                self.sudo().env.company.ultima_respuesta_exo = ultimo_mensaje

                if 'identificacion' in contenido:
                    if self.vat != contenido.get('identificacion'):
                        raise UserError(_('El código de exoneración no concuerda con la cédula del socio de negocio.'))
                    fecha_emision = datetime.strptime(str(contenido.get('fechaEmision'))[:10], '%Y-%m-%d')
                    self.date_issue = fecha_emision
                    fecha_vencimiento = datetime.strptime(str(contenido.get('fechaVencimiento'))[:10], '%Y-%m-%d')
                    self.date_expiration = fecha_vencimiento
                    self.percentage_exoneration = float(contenido.get('porcentajeExoneracion'))
                    self.institution_name = contenido.get('nombreInstitucion')
                    if contenido.get('cabys'):
                        self.allowed_cabys_ids = [(0, 0, {'name': code}) for code in contenido.get('cabys')]

                    tipo_documento = contenido.get('tipoDocumento')

                    autorizacion = self.env['aut.ex'].sudo().search([('code',
                                                                      '=',
                                                                      tipo_documento.get('codigo')),
                                                                     ('active', '=', True)], limit=1)

                    if len(autorizacion) > 0:
                        self.type_exoneration = autorizacion.id

    def check_exonerations(self):
        clients = self.env["res.partner"].search([("has_exoneration", "=", True),
                                                  ("date_expiration", "<", datetime.today())])
        for client in clients:
            if not client.date_notification or (client.date_notification + timedelta(days=8)) < date.today():
                email_template = client.env.ref("l10n_cr_ticofac.email_template_client_exoneration_expired")
                if email_template:
                    email_template.send_mail(client.id)
                    client.date_notification = date.today()

    # -------------------------------------------------------------------------
    # Functions
    # -------------------------------------------------------------------------
    def write(self, vals):
        _logger.debug('res.partner write vals: %s', vals)
        return super(PartnerElectronic, self).write(vals)