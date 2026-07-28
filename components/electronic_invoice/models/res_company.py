from datetime import datetime, timedelta
import json
import requests
import logging

import phonenumbers

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from . import api_facturae

_logger = logging.getLogger(__name__)

_TIPOS_CONFIRMACION = (
    # Provides listing of types of comprobante confirmations
    ('CCE_sequence_id', 'account.invoice.supplier.accept.',
     'Supplier invoice acceptance sequence'),
    ('CPCE_sequence_id', 'account.invoice.supplier.partial.',
     'Supplier invoice partial acceptance sequence'),
    ('RCE_sequence_id', 'account.invoice.supplier.reject.',
     'Supplier invoice rejection sequence'),
    ('FEC_sequence_id', 'account.invoice.supplier.reject.',
     'Supplier electronic purchase invoice sequence'),
)


class CompanyElectronic(models.Model):
    _name = 'res.company'
    _description = 'Company Electronic'
    _inherit = ['res.company', 'mail.thread']

    # ==============================================================================================
    #                                          COMPANY
    # ==============================================================================================

    commercial_name = fields.Char()
    legal_name = fields.Char(
        string="Nombre Legal"
    )
    activity_id = fields.Many2one(
        comodel_name="economic.activity",
        string="Default economic activity",
        context={
            'active_test': False
        }
    )
    signature = fields.Binary(
        string="Cryptographic Key"
    )
    date_expiration_sign = fields.Datetime(
        string="Due date",
    )
    range_days = fields.Integer(
        string='Days range',
        default=5
    )
    send_user_ids = fields.Many2many(
        comodel_name='res.users',
        relation='res_company_res_sendusers_rel',
        string='Users'
    )
    to_emails = fields.Char(
        string='Notification emails'
    )

    identification_id = fields.Many2one(
        comodel_name="identification.type",
        string="Id Type"
    )
    frm_ws_identificador = fields.Char(
        string="Electronic invoice user"
    )
    frm_ws_password = fields.Char(
        string="Electronic invoice password"
    )

    frm_ws_ambiente = fields.Selection(
        selection=[
            ('disabled', 'Deshabilitado'),
            ('api-stag', 'Pruebas'),
            ('api-prod', 'Producción')
        ],
        string="Environment",
        required=True,
        default='disabled',
        help='Es el ambiente en al cual se le está actualizando el certificado. '
             'Para el ambiente de calidad (stag), para el ambiente de producción (prod). '
             'Requerido.'
    )

    frm_pin = fields.Char(
        string="Pin",
        help='Es el pin correspondiente al certificado. Requerido'
    )

    sucursal_MR = fields.Integer(
        string="Sucursal para secuencias de MRs",
        default="1"
    )

    terminal_MR = fields.Integer(
        string="Terminal para secuencias de MRs",
        default="1"
    )

    CCE_sequence_id = fields.Many2one(
        comodel_name='ir.sequence',
        string='Secuencia Aceptación',
        help='Secuencia de confirmacion de aceptación de comprobante electrónico. Dejar en blanco '
             'y el sistema automaticamente se lo creará.',
        readonly=False,
        copy=False
    )

    CPCE_sequence_id = fields.Many2one(
        comodel_name='ir.sequence',
        string='Secuencia Parcial',
        help='Secuencia de confirmación de aceptación parcial de comprobante electrónico. Dejar '
             'en blanco y el sistema automáticamente se lo creará.',
        readonly=False,
        copy=False
    )
    RCE_sequence_id = fields.Many2one(
        comodel_name='ir.sequence',
        string='Secuencia Rechazo',
        help='Secuencia de confirmación de rechazo de comprobante electrónico. Dejar '
             'en blanco y el sistema automáticamente se lo creará.',
        readonly=False,
        copy=False
    )
    FEC_sequence_id = fields.Many2one(
        comodel_name='ir.sequence',
        string='Secuencia de Facturas Electrónicas de Compra',
        readonly=False,
        copy=False
    )

    invoice_qr_type = fields.Selection(
        selection=[
            ('by_url', 'Invoice Url'),
            ('by_info', 'Invoice Text Information')
        ],
        default='by_url',
        required=True
    )
    invoice_field_ids = fields.One2many(
        comodel_name='invoice.qr.fields',
        inverse_name='company_id',
        string="Invoice Field's"
    )

    # Se agrega campos para consultar información de exoneraciones
    ultima_respuesta_exo = fields.Text(
        string="Last API EXONET Response",
        help="Last API EXONET Response, this allows debugging errors if they exist"
    )
    url_base_exo = fields.Char(
        string="URL Base EXONET",
        help="URL Base ENDPOINT EXONET",
        default="https://api.hacienda.go.cr/fe/ex?"
    )

    # === Campos para consulta de Hacienda === #
    url_base = fields.Char(
        string="URL Base",
        help="URL Base of the END POINT",
        default="https://api.hacienda.go.cr/fe/ae?"
    )
    url_base_yo_contribuyo = fields.Char(
        string="URL Base Yo Contribuyo",
        help="URL Base Yo Contribuyo",
        default="https://api.hacienda.go.cr/fe/mifacturacorreo?"
    )
    get_tributary_information = fields.Boolean(default=True)
    get_yo_contribuyo_information = fields.Boolean(default=False)
    usuario_yo_contribuyo = fields.Char(
        string="Yo Contribuyo User",
        help="Yo Contribuyo Developer Identification"
    )
    token_yo_contribuyo = fields.Char(
        string="Yo Contribuyo Token",
        help="Yo Contribuyo Token provided by Ministerio de Hacienda"
    )
    ultima_respuesta_yo_contribuyo = fields.Text(
        string="Latest Yo Contribuyo API response",
        help="Last API Response, this allows debugging errors if they exist"
    )
    ultima_respuesta = fields.Text(
        string="Latest Hacienda API response",
        help="Last API Response, this allows debugging errors if they exist"
    )

    # invoice_is_electronic Boolean
    invoice_is_electronic = fields.Boolean(
        string="Invoice Electronic",
        help='Use this option if you use electronic invoice',
        default=False
    )
    invoice_provider_type = fields.Selection(
        selection=[
            ('external', 'Proveedor Externo'),
            ('inhouse', 'Desarrollo Local')
        ],
        string="Provider Type",
        required=True,
        default='inhouse',
        help='Tipo de proveedor de servicios de facturación electrónica,'
             ' se utiliza para en el encabezado de los documentos electronicos'
    )
    invoice_provider_identification = fields.Char(
        string="Provider Identification",
        help='Identificación del proveedor de servicios de facturación electrónica'
    )

    payment_method_default_id = fields.Many2one(
        'payment.methods',
        string="Medio de Pago por Defecto (FE CR)",
        help="Medio de pago predeterminado para las facturas electrónicas de Costa Rica."
    )

    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------

    @api.constrains('invoice_qr_type', 'invoice_field_ids')
    def check_invoice_field_ids(self):
        if self.invoice_qr_type == 'by_info' and not self.invoice_field_ids:
            raise UserError(_("Please Add Invoice Field's"))

    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------

    @api.onchange('phone')
    def _onchange_phone(self):
        if self.phone:
            phone = phonenumbers.parse(self.phone, self.country_id.code)
            valid = phonenumbers.is_valid_number(phone)
            if not valid:
                alert = {
                    'title': 'Atención',
                    'message': 'Número de teléfono inválido'
                }
                return {'value': {'phone': ''}, 'warning': alert}

    @api.onchange('signature', 'frm_pin')
    def _onchange_signature(self):
        if self.signature and self.frm_pin:
            try:
                self.date_expiration_sign = api_facturae.p12_expiration_date(
                    self.signature, self.frm_pin
                )
            except Exception:
                self.date_expiration_sign = False

    # -------------------------------------------------------------------------
    # PUBLIC ACTIONS
    # -------------------------------------------------------------------------

    def test_get_token(self):
        self.get_expiration_date()
        token_m_h = api_facturae.get_token_hacienda(
            self.env.user, self.frm_ws_ambiente)
        if token_m_h:
            self.message_post(
                subject=_('Info'),
                body=_("Token Correcto"))
        else:
            self.message_post(
                subject=_('Error'),
                body=_("Datos Incorrectos"))

    def action_get_economic_activities(self):
        if self.vat:
            json_response = api_facturae.get_economic_activities(self)

            self.env.cr.execute('update economic_activity set active=False')

            self.message_post(subject=_('Actividades Económicas'),
                              body=_('Aviso!.\n Cargando actividades económicas desde Hacienda'))

            if json_response["status"] == 200:
                activities = json_response["activities"]
                activities_codes = list([])
                for activity in activities:
                    if activity["estado"] == "A":
                        activities_codes.append(activity["codigo"])

                economic_activities = self.env['economic.activity'].with_context(active_test=False).search([
                    ('code', 'in', activities_codes)])

                for activity in economic_activities:
                    activity.active = True

                self.legal_name = json_response["name"]
            else:
                alert = {
                    'title': json_response["status"],
                    'message': json_response["text"]
                }
                return {'value': {'vat': ''}, 'warning': alert}
        else:
            alert = {
                'title': 'Atención',
                'message': _('Company VAT is invalid')
            }
            return {'value': {'vat': ''}, 'warning': alert}

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """ Try to automatically add the Comprobante Confirmation sequence to the company.
            It will attempt to create and assign before storing. The sequence that is
            created will be coded with the following syntax:
                account.invoice.supplier.<tipo>.<company_name>
            where tipo is: accept, partial or reject, and company_name is either the first word
            of the name or commercial name.
        """
        companies = super().create(vals_list)
        for company in companies:
            company.try_create_configuration_sequences()
        return companies

    def write(self, vals):
        if vals.get('date_expiration_sign') or vals.get('range_days'):
            cron = self.env.ref('l10n_cr_ticofac.ir_cron_send_expiration_notice', False)

            if not self.range_days:
                return super().write(vals)

            date_expiration_sign = vals.get('date_expiration_sign') and \
                                   vals['date_expiration_sign'] or self.date_expiration_sign
            # date_expiration_sign = vals.get('date_expiration_sign') and \
            #     datetime.strptime(vals['date_expiration_sign'], '%Y-%m-%d %H:%M:%S') or self.date_expiration_sign
            if date_expiration_sign:
                if isinstance(date_expiration_sign, str):
                    date_expiration_sign = datetime.strptime(date_expiration_sign, '%Y-%m-%d %H:%M:%S')

            range_days = vals.get('range_days') or self.range_days
            next_call = date_expiration_sign - timedelta(days=range_days)
            new_values = {
                'nextcall': next_call
            }

            cron.write(new_values)

        return super().write(vals)

    def try_create_configuration_sequences(self):
        """ Try to automatically add the Comprobante Confirmation sequence to the company.
            It will first check if sequence already exists before attempt to create. The s
            equence is coded with the following syntax:
                account.invoice.supplier.<tipo>.<company_name>
            where tipo is: accept, partial or reject, and company_name is either the first word
            of the name or commercial name.
        """
        company_subname = self.commercial_name
        if not company_subname:
            company_subname = getattr(self, 'name')
        company_subname = company_subname.split(' ')[0].lower()
        ir_sequence = self.env['ir.sequence']
        to_write = {}
        for field, seq_code, seq_name in _TIPOS_CONFIRMACION:
            if not getattr(self, field, None):
                seq_code += company_subname
                seq = self.env.ref(seq_code, raise_if_not_found=False) or ir_sequence.create({
                    'name': seq_name,
                    'code': seq_code,
                    'implementation': 'standard',
                    'padding': 10,
                    'use_date_range': False,
                    'company_id': getattr(self, 'id'),
                })
                to_write[field] = seq.id

        if to_write:
            self.write(to_write)

    # -------------------------------------------------------------------------
    # CRON
    # -------------------------------------------------------------------------

    def _cron_send_email_notifications(self):
        today = datetime.now()
        date_due = self.env.company.date_expiration_sign
        range_day = self.env.company.range_days

        range_date = date_due - timedelta(days=range_day)
        if today >= range_date:
            template = self.env.ref('l10n_cr_ticofac.email_template_edi_expiration_notice', False)

            template_values = {
                'email_to': '${object.email|safe}',
                'email_cc': False,
                'auto_delete': True,
                'partner_to': False,
                'scheduled_date': False,
            }

            template.write(template_values)

            for user in self.env.company.send_user_ids:
                if user.email:
                    template.with_context(lang=user.lang).send_mail(user.id, force_send=True, raise_exception=True)

    # -------------------------------------------------------------------------
    # TOOLING
    # -------------------------------------------------------------------------

    def get_days_left(self):
        today = datetime.today()
        date_due = self.date_expiration_sign
        range_days = date_due - today if date_due else today - today
        return range_days.days

    def get_message_to_send(self):
        days_left = self.get_days_left()

        message = ''
        if days_left >= 0:
            message = f'Su llave criptográfica está a punto de expirar, le quedan {days_left} día(s)'
        else:
            message = f'No podrá validar porque su llave criptográfica expiró hace {abs(days_left)} día(s)'

        return message

    def get_expiration_date(self):
        self.ensure_one()
        if not self.signature or not self.frm_pin:
            raise UserError(_("Debe cargar la llave criptográfica e ingresar su PIN."))
        try:
            expiration = api_facturae.p12_expiration_date(
                self.signature, self.frm_pin
            )
        except Exception as error:
            _logger.warning(
                "No fue posible leer el certificado de la compañía %s: %s",
                self.id,
                error,
            )
            raise UserError(
                _("No fue posible leer la llave criptográfica. Verifique el archivo y el PIN.")
            ) from error
        self.date_expiration_sign = expiration
        return expiration

    def limpiar_cedula(self, vat):
        if vat:
            return ''.join(i for i in vat if i.isdigit())

    def definir_informacion(self, cedula):
        url_base_yo_contribuyo = self.url_base_yo_contribuyo
        usuario_yo_contribuyo = self.usuario_yo_contribuyo
        token_yo_contribuyo = self.token_yo_contribuyo
        url_base = self.url_base

        get_tributary_information = self.get_tributary_information
        get_yo_contribuyo_information = self.get_yo_contribuyo_information

        if url_base and get_tributary_information:
            url_base = url_base.strip()

            if url_base[-1:] == '/':
                url_base = url_base[:-1]

            end_point = url_base + 'identificacion=' + cedula
            
            _logger.info('HACIENDA API - URL: %s', end_point)
            _logger.info('HACIENDA API - Cedula: %s', cedula)

            headers = {
                'content-type': 'application/json'
            }
            try:
                peticion = requests.get(end_point, headers=headers, timeout=10)

                ultimo_mensaje = 'Datetime: %s\n' % str(datetime.now())
                ultimo_mensaje += 'URL: %s\n' % end_point
                ultimo_mensaje += 'Code: %s\n' % str(peticion.status_code)
                ultimo_mensaje += 'Headers: %s\n' % str(dict(peticion.headers))
                ultimo_mensaje += 'Message: %s' % str(peticion._content.decode())

                self.ultima_respuesta = ultimo_mensaje

                if peticion.status_code in (200, 202) and len(peticion._content) > 0:
                    contenido = json.loads(str(peticion._content, 'utf-8'))

                    if contenido.get('nombre') and contenido.get('tipoIdentificacion'):
                        # Actualizar el nombre de la compañía con el nombre obtenido de Hacienda
                        self.name = contenido.get('nombre')
                        _logger.info('Estado: %s' % contenido.get('situacion', {}).get('estado'))

                        if 'identification_id' in self._fields:
                            clasificacion = contenido.get('tipoIdentificacion')
                            self.identification_id = self.env['identification.type'].search(
                                [
                                    ('code', '=', clasificacion)
                                ],
                                limit=1
                            ).id

                    if contenido.get('actividades') and 'activity_id' in self._fields:
                        for act in contenido.get('actividades'):
                            if act.get('estado') == 'A':
                                self.activity_id = self.env['economic.activity'].search(
                                    [
                                        ('code', '=', str(act.get('codigo')))
                                    ],
                                    limit=1
                                ).id
                                break
                    
                    # Mostrar mensaje de éxito
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Consulta Exitosa',
                            'message': f'Se ha actualizado el nombre de la compañía a: {self.name}',
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    # Mostrar mensaje de error específico según el código de estado
                    if peticion.status_code == 403:
                        error_message = 'Error 403: Acceso denegado. Verifique que la cédula sea válida y que el servicio de Hacienda esté disponible.'
                    elif peticion.status_code == 404:
                        error_message = 'Error 404: Contribuyente no encontrado en el sistema de Hacienda.'
                    elif peticion.status_code == 500:
                        error_message = 'Error 500: Error interno del servidor de Hacienda. Intente más tarde.'
                    else:
                        error_message = f'No se pudo obtener información del contribuyente. Código: {peticion.status_code}'
                    
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Error de Comunicación',
                            'message': error_message,
                            'type': 'warning',
                            'sticky': True,
                        }
                    }
            except Exception as e:
                message = 'The query service is unavailable at this moment: %s' % str(e)
                _logger.info(message)
                ultimo_mensaje = 'Datetime: %s\n' % str(datetime.now())
                ultimo_mensaje += 'Message: %s' % message

                self.ultima_respuesta = ultimo_mensaje
                
                # Mostrar mensaje de error cuando hay una excepción
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error de Comunicación',
                        'message': f'Error al comunicarse con Hacienda: {str(e)}',
                        'type': 'error',
                        'sticky': True,
                    }
                }

    def action_consultar_contribuyente(self):
        """Acción para consultar información del contribuyente desde Hacienda"""
        if self.vat:
            cedula_limpia = self.limpiar_cedula(self.vat)
            if cedula_limpia:
                # Llamar a definir_informacion y devolver su resultado directamente
                # ya que ahora maneja los mensajes de éxito y error
                return self.definir_informacion(cedula_limpia)
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Por favor ingrese un número de identificación válido.',
                        'type': 'warning',
                        'sticky': False,
                    }
                }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Por favor ingrese un número de identificación.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
     ##
     ## Cambio para tomar configuraciones para el POS
     ## By: Singulary
    
    def _load_pos_data_fields(self, config_id):
        # En v18 este hook define qué campos de res.company viajan al POS
        fields = super()._load_pos_data_fields(config_id)
        if 'invoice_is_electronic' not in fields:
            fields.append('invoice_is_electronic')
        return fields

    @api.onchange('vat')
    def onchange_vat(self):
        if self.vat:
            cedula_limpia = self.limpiar_cedula(self.vat)
            if cedula_limpia:
                return self.definir_informacion(cedula_limpia)
