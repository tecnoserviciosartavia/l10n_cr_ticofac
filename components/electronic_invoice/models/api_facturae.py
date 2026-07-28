# -*- coding: utf-8 -*-
import base64
import datetime
import io
import json
import logging
import os
import random
import re
import time
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from html import escape  # escapes &, <, > … for XML safety
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import phonenumbers
import pytz
import requests
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from lxml import etree
from odoo import _
from odoo.exceptions import UserError

from . import fe_enums

# PARA VALIDAR JSON DE RESPUESTA
# from .. import extensions

_logger = logging.getLogger(__name__)


def sign_xml(cert, password, xml_string):
    xml = ElementTree.fromstring(xml_string)
    ElementTree.register_namespace('', xml.tag.split('}')[0][1:] if '}' in xml.tag else '')
    ElementTree.register_namespace('ds', 'http://www.w3.org/2000/09/xmldsig#')
    ElementTree.register_namespace('dsig-filter2', 'http://www.w3.org/2002/06/xmldsig-filter2')
    ElementTree.register_namespace('xades', 'http://uri.etsi.org/01903/v1.3.2#')
    ElementTree.indent(xml)

    canonical_xml = ElementTree.canonicalize(ElementTree.tostring(xml))
    document_digest = base64.b64encode(sha256(canonical_xml.encode()).digest()).decode()
    private_key, certificate, _ = pkcs12.load_key_and_certificates(base64.b64decode(cert), password.encode('utf-8'))
    cert_digest = base64.b64encode(certificate.fingerprint(SHA256())).decode()
    cert_base64 = base64.b64encode(certificate.public_bytes(Encoding.DER)).decode()
    issuer = certificate.issuer.rfc4514_string()
    serial = certificate.serial_number
    signing_time = datetime.datetime.now().isoformat(timespec='seconds') + 'Z'
    policy_id = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/Resoluci%C3%B3n_General_sobre_disposiciones_t%C3%A9cnicas_comprobantes_electr%C3%B3nicos_para_efectos_tributarios.pdf';
    policy_digest = 'DWxin1xWOeI8OuWQXazh4VjLWAaCLAA954em7DMh0h8=';

    signed_properties = (
    f'<xades:SignedProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" Id="p1">\n'
    f'          <xades:SignedSignatureProperties>\n'
    f'            <xades:SigningTime>{signing_time}</xades:SigningTime>\n'
    f'            <xades:SigningCertificate>\n'
    f'              <xades:Cert>\n'
    f'                <xades:CertDigest>\n'
    f'                  <ds:DigestMethod xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>\n'
    f'                  <ds:DigestValue xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{cert_digest}</ds:DigestValue>\n'
    f'                </xades:CertDigest>\n'
    f'                <xades:IssuerSerial>\n'
    f'                  <ds:X509IssuerName xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{issuer}</ds:X509IssuerName>\n'
    f'                  <ds:X509SerialNumber xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{serial}</ds:X509SerialNumber>\n'
    f'                </xades:IssuerSerial>\n'
    f'              </xades:Cert>\n'
    f'            </xades:SigningCertificate>\n'
    f'            <xades:SignaturePolicyIdentifier>\n'
    f'              <xades:SignaturePolicyId>\n'
    f'                <xades:SigPolicyId>\n'
    f'                  <xades:Identifier>{policy_id}</xades:Identifier>\n'
    f'                </xades:SigPolicyId>\n'
    f'                <xades:SigPolicyHash>\n'
    f'                  <ds:DigestMethod xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>\n'
    f'                  <ds:DigestValue xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{policy_digest}</ds:DigestValue>\n'
    f'                </xades:SigPolicyHash>\n'
    f'              </xades:SignaturePolicyId>\n'
    f'            </xades:SignaturePolicyIdentifier>\n'
    f'          </xades:SignedSignatureProperties>\n'
    f'          <xades:SignedDataObjectProperties>\n'
    f'            <xades:DataObjectFormat ObjectReference="#r1">\n'
    f'              <xades:MimeType>text/xml</xades:MimeType>\n'
    f'            </xades:DataObjectFormat>\n'
    f'          </xades:SignedDataObjectProperties>\n'
    f'        </xades:SignedProperties>')

    properties_digest = base64.b64encode(sha256(signed_properties.encode()).digest()).decode()

    signed_info = (
    f'<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">\n'
    f'      <ds:CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"></ds:CanonicalizationMethod>\n'
    f'      <ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"></ds:SignatureMethod>\n'
    f'      <ds:Reference Id="r1" URI="">\n'
    f'        <ds:Transforms>\n'
    f'          <ds:Transform Algorithm="http://www.w3.org/2002/06/xmldsig-filter2">\n'
    f'            <dsig-filter2:XPath xmlns:dsig-filter2="http://www.w3.org/2002/06/xmldsig-filter2" Filter="subtract">/descendant::ds:Signature</dsig-filter2:XPath>\n'
    f'          </ds:Transform>\n'
    f'          <ds:Transform Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"></ds:Transform>\n'
    f'        </ds:Transforms>\n'
    f'        <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>\n'
    f'        <ds:DigestValue>{document_digest}</ds:DigestValue>\n'
    f'      </ds:Reference>\n'
    f'      <ds:Reference Type="http://uri.etsi.org/01903#SignedProperties" URI="#p1">\n'
    f'        <ds:Transforms>\n'
    f'          <ds:Transform Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"></ds:Transform>\n'
    f'        </ds:Transforms>\n'
    f'        <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>\n'
    f'        <ds:DigestValue>{properties_digest}</ds:DigestValue>\n'
    f'      </ds:Reference>\n'
    f'    </ds:SignedInfo>')

    # Sign the signed info
    signature_value = base64.b64encode(private_key.sign(signed_info.encode(), padding.PKCS1v15(), SHA256())).decode()

    signature = (
    f'<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="s1">\n'
    f'    {signed_info}\n'
    f'    <ds:SignatureValue Id="v1">{signature_value}</ds:SignatureValue>\n'
    f'    <ds:KeyInfo>\n'
    f'      <ds:X509Data>\n'
    f'        <ds:X509Certificate>{cert_base64}</ds:X509Certificate>\n'
    f'      </ds:X509Data>\n'
    f'    </ds:KeyInfo>\n'
    f'    <ds:Object>\n'
    f'      <xades:QualifyingProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" Target="#s1">\n'
    f'        {signed_properties}\n'
    f'      </xades:QualifyingProperties>\n'
    f'    </ds:Object>\n'
    f'  </ds:Signature>')

    # Append signature to the canonical XML
    xml_tree = ElementTree.fromstring(canonical_xml)
    signature_tree = ElementTree.fromstring(signature)
    xml_tree.append(signature_tree)

    return ElementTree.tostring(xml_tree, encoding='UTF-8', method='xml', xml_declaration=True)

def get_time_hacienda():
    now_utc = datetime.datetime.now(pytz.timezone('UTC'))
    now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
    date_cr = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")

    return date_cr

# Utilizada para establecer un limite de caracteres en la cedula del cliente, no mas de 20
# de lo contrario hacienda lo rechaza
def limit(texto, limit):
    return (texto[:limit - 3] + '...') if len(texto) > limit else texto

def get_mr_sequencevalue(inv):
    # Verificamos si el ID del mensaje receptor es válido
    mr_mensaje_id = int(inv.state_invoice_partner)
    if mr_mensaje_id is None:
        raise UserError(_('No se ha proporcionado un ID válido para el MR.'))
    elif mr_mensaje_id < 1 or mr_mensaje_id > 3:
        raise UserError(_('El ID del mensaje receptor es inválido.'))

    if inv.state_invoice_partner == '1':
        detalle_mensaje = 'Aceptado'
        tipo = 1
        tipo_documento = fe_enums.TipoDocumento['CCE']
        sequence = inv.env['ir.sequence'].next_by_code(
            'sequence.electronic.doc.confirmation')

    elif inv.state_invoice_partner == '2':
        detalle_mensaje = 'Aceptado parcial'
        tipo = 2
        tipo_documento = fe_enums.TipoDocumento['CPCE']
        sequence = inv.env['ir.sequence'].next_by_code(
            'sequence.electronic.doc.partial.confirmation')
    else:
        detalle_mensaje = 'Rechazado'
        tipo = 3
        tipo_documento = fe_enums.TipoDocumento['RCE']
        sequence = inv.env['ir.sequence'].next_by_code(
            'sequence.electronic.doc.reject')

    return {'detalle_mensaje': detalle_mensaje, 'tipo': tipo, 'tipo_documento': tipo_documento, 'sequence': sequence}

def get_consecutivo_hacienda(tipo_documento, consecutivo, sucursal_id, terminal_id):

    tipo_doc = fe_enums.TipoDocumento[tipo_documento]

    inv_consecutivo = str(consecutivo).zfill(10)
    inv_sucursal = str(sucursal_id).zfill(3)
    inv_terminal = str(terminal_id).zfill(5)

    consecutivo_mh = inv_sucursal + inv_terminal + tipo_doc + inv_consecutivo

    return consecutivo_mh


def get_clave_hacienda(
    doc,
    tipo_documento,
    consecutivo,
    sucursal_id,
    terminal_id,
    situacion="normal",
    fecha_emision=None,
):
    """
    Generate the 50-character electronic key (Clave) for Hacienda.

    Args:
        doc: Document record (invoice, payment, etc.) for company info
        tipo_documento: Document type code (FE, NC, ND, TE, REP, etc.)
        consecutivo: 10-digit consecutive number
        sucursal_id: Branch ID
        terminal_id: Terminal ID
        situacion: Document situation ('normal' or 'contingencia')
        fecha_emision: Optional date to use in the key. If None, uses doc.invoice_date.
                       For REP, pass the actual emission date to match FechaEmision in XML.

    Returns:
        dict with 'clave' (50-char key) and 'consecutivo' (20-char consecutive)
    """
    tipo_doc = fe_enums.TipoDocumento[tipo_documento]

    # Verificamos si el consecutivo indicado corresponde a un numero
    inv_consecutivo = re.sub('[^0-9]', '', consecutivo)
    if len(inv_consecutivo) != 10:
        raise UserError(_('La numeración debe de tener 10 dígitos'))

    # Verificamos la sucursal y terminal
    inv_sucursal = re.sub('[^0-9]', '', str(sucursal_id)).zfill(3)
    inv_terminal = re.sub('[^0-9]', '', str(terminal_id)).zfill(5)

    # Armamos el consecutivo pues ya tenemos los datos necesarios
    consecutivo_mh = inv_sucursal + inv_terminal + tipo_doc + inv_consecutivo

    if not doc.company_id.identification_id:
        raise UserError(_('Seleccione el tipo de identificación del emisor en el pérfil de la compañía'))

    # Obtenemos el número de identificación del Emisor y lo validamos númericamente
    inv_cedula = re.sub('[^0-9]', '', doc.company_id.vat)

    # Validamos el largo de la cadena númerica de la cédula del emisor
    if doc.company_id.identification_id.code == '01' and len(inv_cedula) != 9:
        raise UserError(_('La Cédula Física del emisor debe de tener 9 dígitos'))
    elif doc.company_id.identification_id.code == '02' and len(inv_cedula) != 10:
        raise UserError(_('La Cédula Jurídica del emisor debe de tener 10 dígitos'))
    elif doc.company_id.identification_id.code == '03' and len(inv_cedula) not in (11, 12):
        raise UserError(_('La identificación DIMEX del emisor debe de tener 11 o 12 dígitos'))
    elif doc.company_id.identification_id.code == '04' and len(inv_cedula) != 10:
        raise UserError(_('La identificación NITE del emisor debe de tener 10 dígitos'))

    inv_cedula = str(inv_cedula).zfill(12)

    # Limitamos la cedula del emisor a 20 caracteres o nos dará error
    cedula_emisor = limit(inv_cedula, 20)

    # Validamos la situación del comprobante electrónico
    situacion_comprobante = fe_enums.SituacionComprobante.get(situacion)
    if not situacion_comprobante:
        raise UserError(_(f'La situación indicada para el comprobante electŕonico es inválida: {situacion}'))

    # Creamos la fecha para la clave
    # Use provided fecha_emision or fall back to doc.invoice_date
    if fecha_emision:
        # fecha_emision can be a date object or datetime
        doc_date = fecha_emision
    else:
        doc_date = doc.invoice_date

    dia = str(doc_date.day).zfill(2)
    mes = str(doc_date.month).zfill(2)
    anno = str(doc_date.year)[2:]
    cur_date = dia + mes + anno

    phone = phonenumbers.parse(doc.company_id.phone,
                               doc.company_id.country_id and doc.company_id.country_id.code or 'CR')
    codigo_pais = str(phone and phone.country_code or 506)

    # Creamos un código de seguridad random
    codigo_seguridad = str(random.randint(1, 99999999)).zfill(8)

    clave_hacienda = codigo_pais + cur_date + cedula_emisor + \
        consecutivo_mh + situacion_comprobante + codigo_seguridad

    return {'length': len(clave_hacienda), 'clave': clave_hacienda, 'consecutivo': consecutivo_mh}


# Variables para poder manejar el Refrescar del Token
last_tokens = {}
last_tokens_time = {}
last_tokens_expire = {}
last_tokens_refresh = {}

def get_token_hacienda(inv, tipo_ambiente, force_refresh=False):
    global last_tokens
    global last_tokens_time
    global last_tokens_expire
    global last_tokens_refresh

    if force_refresh:
        last_tokens.pop(inv.company_id.id, None)
        last_tokens_time.pop(inv.company_id.id, None)
        last_tokens_expire.pop(inv.company_id.id, None)
        last_tokens_refresh.pop(inv.company_id.id, None)

    token = last_tokens.get(inv.company_id.id, False)
    token_time = last_tokens_time.get(inv.company_id.id, False)
    token_expire = last_tokens_expire.get(inv.company_id.id, 0)
    current_time = time.time()

    if token and (current_time - token_time < token_expire - 10):
        token_hacienda = token
    else:
        headers = {}
        data = {
            'client_id': tipo_ambiente,
            'client_secret': '',
            'grant_type': 'password',
            'username': inv.company_id.frm_ws_identificador,
            'password': inv.company_id.frm_ws_password
        }

        # establecer el ambiente al cual me voy a conectar
        endpoint = fe_enums.UrlHaciendaToken[tipo_ambiente]

        _logger.info("FECR - intentando obtener token en %s con usuario %s.", endpoint, inv.company_id.frm_ws_identificador)

        try:
            # enviando solicitud post y guardando la respuesta como un objeto json
            response = requests.request(
                "POST", endpoint, data=data, headers=headers, timeout=20)
            response_json = response.json()

            # LOG seguro y detallado
            _logger.info("FECR - token status=%s", response.status_code)
            _logger.debug("FECR - token headers=%s", dict(response.headers))
            # F841 local variable 'respuesta' is assigned to but never used
            # respuesta = extensions.response_validator.assert_valid_schema(response_json, 'token.json')

            if 200 <= response.status_code <= 299:
                token_hacienda = response_json.get('access_token')
                last_tokens[inv.company_id.id] = token_hacienda
                last_tokens_time[inv.company_id.id] = time.time()
                last_tokens_expire[inv.company_id.id] = response_json.get('expires_in')
                last_tokens_refresh[inv.company_id.id] = response_json.get('refresh_expires_in')
            else:
                _logger.error('FECR - token_hacienda failed.  error: %s' % (response.status_code))
                _logger.error("FECR - token_hacienda failed. status=%s body=%s", response.status_code, response.text)

                # Mensaje más descriptivo para el usuario
                error_msg = response_json.get('error_description', response.text) if response_json else response.text
                raise UserError(_(
                    'Error obteniendo token de Hacienda.\n\n'
                    'Código de error: %s\n'
                    'Descripción: %s\n'
                ) % (response.status_code, error_msg))

        except requests.exceptions.RequestException as e:
            _logger.exception("FECR - error de red/timeout al pedir token")
            raise UserError(_(
                'Error de conexión con Hacienda.\n\n'
                'No se pudo conectar al servidor de Hacienda para obtener el token.\n'
                'Verifique su conexión a internet e intente nuevamente.\n\n'
                'Detalle técnico: %s'
            ) % str(e))

    return token_hacienda

def refresh_token_hacienda(tipo_ambiente, token):

    headers = {}
    data = {
        'client_id': tipo_ambiente,
        'client_secret': '',
        'grant_type': 'refresh_token',
        'refresh_token': token
    }

    # establecer el ambiente al cual me voy a conectar
    endpoint = fe_enums.UrlHaciendaToken[tipo_ambiente]

    try:
        # enviando solicitud post y guardando la respuesta como un objeto json
        response = requests.request("POST", endpoint, data=data, headers=headers)
        response_json = response.json()
        token_hacienda = response_json.get('access_token')
        return token_hacienda
    except ImportError:
        raise Warning(_('Error Refrescando el Token desde MH'))

def gen_xml_mr_43(clave, cedula_emisor, fecha_emision, id_mensaje,
                  detalle_mensaje, cedula_receptor,
                  consecutivo_receptor,
                  monto_impuesto=0, total_factura=0,
                  codigo_actividad=False,
                  condicion_impuesto=False,
                  monto_total_impuesto_acreditar=False,
                  monto_total_gasto_aplicable=False):
    # Verificamos si la clave indicada corresponde a un numeros
    if clave:
        mr_clave = re.sub('[^0-9]', '', clave)
    else:
        mr_clave = False
    if len(mr_clave) != 50:
        raise UserError(_('La clave a utilizar es inválida. Debe contener al menos 50 digitos'))

    
    mr_cedula_emisor =  re.sub('[^0-9]', '', cedula_emisor)
    mr_cedula_receptor = re.sub('[^0-9]', '', cedula_receptor)
    mr_fecha_emision = fecha_emision
    if mr_fecha_emision is None:
        raise UserError(_('La fecha de emisión en el MR es inválida.'))

    # Verificamos si el ID del mensaje receptor es válido
    mr_mensaje_id = int(id_mensaje)
    if mr_mensaje_id < 1 and mr_mensaje_id > 3:
        raise UserError(_('El ID del mensaje receptor es inválido.'))
    elif mr_mensaje_id is None:
        raise UserError(_('No se ha proporcionado un ID válido para el MR.'))

    

    # Verificamos si el consecutivo indicado para el mensaje receptor corresponde a numeros
    mr_consecutivo_receptor = re.sub('[^0-9]', '', consecutivo_receptor)
    if len(mr_consecutivo_receptor) != 20:
        raise UserError(_('La clave del consecutivo para el mensaje receptor es inválida. '
                        'Debe contener al menos 50 digitos'))

    mr_monto_impuesto = monto_impuesto
    mr_detalle_mensaje = detalle_mensaje
    mr_total_factura = total_factura

    # Iniciamos con la creación del mensaje Receptor
    sb = StringBuilder()
    sb.append('<MensajeReceptor xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ')
    sb.append('xmlns="https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/mensajeReceptor" ')
    sb.append('xsi:schemaLocation="https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/mensajeReceptor ')
    sb.append('https://www.hacienda.go.cr/ATV/ComprobanteElectronico/' +
              'docs/esquemas/2024/v4.4/MensajeReceptor_V4.4.xsd">')
    sb.append('<Clave>' + mr_clave + '</Clave>')
    sb.append('<NumeroCedulaEmisor>' + mr_cedula_emisor + '</NumeroCedulaEmisor>')
    sb.append('<FechaEmisionDoc>' + mr_fecha_emision + '</FechaEmisionDoc>')
    sb.append('<Mensaje>' + str(mr_mensaje_id) + '</Mensaje>')

    if mr_detalle_mensaje is not None:
        sb.append('<DetalleMensaje>' + escape(mr_detalle_mensaje) + '</DetalleMensaje>')

    if mr_monto_impuesto is not None and mr_monto_impuesto > 0:
        sb.append('<MontoTotalImpuesto>' + str(mr_monto_impuesto) + '</MontoTotalImpuesto>')

    if codigo_actividad:
        sb.append('<CodigoActividad>' + str(codigo_actividad) + '</CodigoActividad>')

    sb.append('<CondicionImpuesto>' + str(condicion_impuesto) + '</CondicionImpuesto>')

    # TODO: Estar atento a la publicación de Hacienda de cómo utilizar esto
    if monto_total_impuesto_acreditar:
        sb.append('<MontoTotalImpuestoAcreditar>' +str(monto_total_impuesto_acreditar) + '</MontoTotalImpuestoAcreditar>')

    # TODO: Estar atento a la publicación de Hacienda de cómo utilizar esto
    if monto_total_gasto_aplicable:
        sb.append('<MontoTotalDeGastoAplicable>' + str(monto_total_gasto_aplicable) + '</MontoTotalDeGastoAplicable>')

    if mr_total_factura is not None and mr_total_factura > 0:
        sb.append('<TotalFactura>' + str(mr_total_factura) + '</TotalFactura>')
    else:
        raise UserError(_('El monto Total de la Factura para el Mensaje Receptro es inválido'))

    sb.append('<NumeroCedulaReceptor>' + mr_cedula_receptor + '</NumeroCedulaReceptor>')
    sb.append('<NumeroConsecutivoReceptor>' + mr_consecutivo_receptor + '</NumeroConsecutivoReceptor>')
    sb.append('</MensajeReceptor>')

    return str(sb)

def gen_xml_v43(inv, sale_conditions, total_servicio_gravado,
                total_servicio_exento,total_servicio_no_sujeto, totalServExonerado,
                total_mercaderia_gravado, total_mercaderia_exento,
                totalMercExonerada,total_mercaderia_no_sujeto, totalOtrosCargos, total_iva_devuelto, base_total,
                total_impuestos_asum_emisor_fabrica,total_impuestos,total_desgloce_impuesto, total_descuento, lines,
                otrosCargos, currency_rate, invoice_comments,
                tipo_documento_referencia, numero_documento_referencia,
                fecha_emision_referencia, codigo_referencia, razon_referencia):

    numero_linea = 0
    payment_methods_id = []

    if inv._name == 'pos.order':
        plazo_credito = '0'
        for payment in inv.payment_ids:
            if not payment.payment_method_id.sequence:
                payment_methods_id.append('01')
            else:
                payment_methods_id.append(str(payment.payment_method_id.sequence))
        cod_moneda = str(inv.company_id.currency_id.name)
        invoice_ref = False
    else:
        payment_methods_id.append(str(inv.payment_methods_id.sequence))
        plazo_credito = str(inv.invoice_payment_term_id and inv.invoice_payment_term_id.line_ids[0].nb_days or 0)
        cod_moneda = str(inv.currency_id.name)
        invoice_ref = inv.ref

    if inv.tipo_documento == 'FEC':
        # Para FE de compra, usar siempre el partner comercial fiscal del proveedor.
        issuing_company = inv.partner_id.commercial_partner_id
        receiver_company = inv.company_id
        issuing_company_name = issuing_company.name
    else:
        issuing_company = inv.company_id
        # En ventas, usar el partner comercial fiscal del cliente para la sección Receptor.
        receiver_company = inv.partner_id.commercial_partner_id
        issuing_company_name = issuing_company.legal_name or issuing_company.name

    issuer_location = {
        "Provincia": issuing_company.state_id.code if issuing_company.state_id else False,
        "Cantón": issuing_company.county_id.code if issuing_company.county_id else False,
        "Distrito": issuing_company.district_id.code if issuing_company.district_id else False,
        "Otras señas": issuing_company.street,
    }
    missing_issuer_location = [
        label for label, value in issuer_location.items() if not value
    ]
    if missing_issuer_location:
        raise UserError(
            _(
                "Complete la dirección fiscal del emisor antes de enviar a Hacienda. "
                "Faltan: %s"
            )
            % ", ".join(missing_issuer_location)
        )

    sb = StringBuilder()
    sb.append('<' + fe_enums.tagName[inv.tipo_documento] +
              ' xmlns="' +
              fe_enums.XmlnsHacienda[inv.tipo_documento] + '" ')
    sb.append('xmlns:ds="http://www.w3.org/2000/09/xmldsig#" xmlns:xsd="http://www.w3.org/2001/XMLSchema" ')
    sb.append('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ')
    sb.append('xsi:schemaLocation="' + fe_enums.schemaLocation[inv.tipo_documento] + '">')

    sb.append('<Clave>' + inv.number_electronic + '</Clave>')
    sb.append('<ProveedorSistemas>' +
              (inv.company_id.invoice_provider_identification
               if inv.company_id.invoice_provider_type == 'external'
               else inv.company_id.vat) + '</ProveedorSistemas>')
    # En caso de factura electronica de compra, se invierten Emisor y receptor.
    if inv.tipo_documento == "FEC":
        sb.append('<CodigoActividadEmisor>' + str(inv.partner_economic_activity_id.code) + '</CodigoActividadEmisor>')
        sb.append('<CodigoActividadReceptor>' + str(inv.economic_activity_id.code)  + '</CodigoActividadReceptor>')
    else:
        sb.append('<CodigoActividadEmisor>' + str(inv.economic_activity_id.code) + '</CodigoActividadEmisor>')
    
    if inv.tipo_documento in ["FE", "NC", "ND"] and inv.partner_economic_activity_id.code:
        sb.append('<CodigoActividadReceptor>' + str(inv.partner_economic_activity_id.code) + '</CodigoActividadReceptor>')
    

    sb.append('<NumeroConsecutivo>' + inv.number_electronic[21:41] + '</NumeroConsecutivo>')
    sb.append('<FechaEmision>' + inv.date_issuance + '</FechaEmision>')
    sb.append('<Emisor>')
    sb.append('<Nombre>' + escape(issuing_company_name) + '</Nombre>')
    sb.append('<Identificacion>')
    sb.append('<Tipo>' + str(issuing_company.identification_id.code) + '</Tipo>')
    sb.append('<Numero>' + str(issuing_company.vat) + '</Numero>')
    sb.append('</Identificacion>')
    sb.append('<NombreComercial>' + escape(str(issuing_company.commercial_name or 'No disponible')) + '</NombreComercial>')
    sb.append('<Ubicacion>')
    sb.append("<Provincia>" + str(issuer_location["Provincia"]) + "</Provincia>")
    sb.append("<Canton>" + str(issuer_location["Cantón"]) + "</Canton>")
    sb.append("<Distrito>" + str(issuer_location["Distrito"]) + "</Distrito>")

    # --- Issuer ---
    if issuing_company.neighborhood_id and issuing_company.neighborhood_id.code:
        neighborhood_value = normalize_neighborhood(
            issuing_company.neighborhood_id.name
        )
        if neighborhood_value:
            sb.append(f"<Barrio>{neighborhood_value}</Barrio>")

    sb.append('<OtrasSenas>' + escape(str(issuing_company.street or 'No disponible')) + '</OtrasSenas>')
    sb.append('</Ubicacion>')

    if issuing_company.phone:
        phone = phonenumbers.parse(issuing_company.phone, (issuing_company.country_id.code or 'CR'))
        sb.append('<Telefono>')
        sb.append('<CodigoPais>' + str(phone.country_code) + '</CodigoPais>')
        sb.append('<NumTelefono>' + str(phone.national_number) + '</NumTelefono>')
        sb.append('</Telefono>')

    sb.append('<CorreoElectronico>' + str(issuing_company.email) + '</CorreoElectronico>')
    sb.append('</Emisor>')

    if inv.tipo_documento == 'TE' or (inv.tipo_documento == 'NC' and inv.reference_document_id.code == '04'):
        pass
    else:
        vat = re.sub('[^0-9]', '', receiver_company.vat)
        if not receiver_company.identification_id:
            if len(vat) == 9:  # cedula fisica
                id_code = '01'
            elif len(vat) == 10:  # cedula juridica
                id_code = '02'
            elif len(vat) == 11 or len(vat) == 12:  # dimex
                id_code = '03'
            else:
                id_code = '05'
        else:
            id_code = receiver_company.identification_id.code

        if receiver_company.name:
            sb.append('<Receptor>')
            sb.append('<Nombre>' + escape(str(receiver_company.name[:99])) + '</Nombre>')
            sb.append('<Identificacion>')
            sb.append('<Tipo>' + str(id_code) + '</Tipo>')
            sb.append('<Numero>' + str(vat) + '</Numero>')
            sb.append('</Identificacion>')

            if inv.tipo_documento != 'FEE':
                if receiver_company.state_id and \
                        receiver_company.county_id and \
                        receiver_company.district_id and receiver_company.neighborhood_id:
                    sb.append('<Ubicacion>')
                    sb.append('<Provincia>' + str(receiver_company.state_id.code or '') + '</Provincia>')
                    sb.append('<Canton>' + str(receiver_company.county_id.code or '') + '</Canton>')
                    sb.append('<Distrito>' + str(receiver_company.district_id.code or '') + '</Distrito>')

                    if receiver_company.neighborhood_id and receiver_company.neighborhood_id.code:
                        neighborhood_value = normalize_neighborhood(
                            receiver_company.neighborhood_id.name
                        )
                        if neighborhood_value:
                            sb.append(f"<Barrio>{neighborhood_value}</Barrio>")
                    sb.append('<OtrasSenas>' + escape(str(receiver_company.street or 'No disponible')) + '</OtrasSenas>')
                    sb.append('</Ubicacion>')

            if receiver_company.phone:
                try:
                    phone = phonenumbers.parse(receiver_company.phone, (receiver_company.country_id.code or 'CR'))
                    sb.append('<Telefono>')
                    sb.append('<CodigoPais>' + str(phone.country_code) + '</CodigoPais>')
                    sb.append('<NumTelefono>' + str(phone.national_number) + '</NumTelefono>')
                    sb.append('</Telefono>')
                except:
                    pass

                re_match = r'^(\s?[^\s,]+@[^\s,]+\.[^\s,]+\s?,)*(\s?[^\s,]+@[^\s,]+\.[^\s,]+)$'
                match = receiver_company.email and re.match(re_match, receiver_company.email.lower())
                if match:
                    email_receptor = receiver_company.email
                else:
                    email_receptor = 'indefinido@indefinido.com'
                sb.append('<CorreoElectronico>' + str(email_receptor) + '</CorreoElectronico>')

            sb.append('</Receptor>')

    sb.append('<CondicionVenta>' + str(sale_conditions) + '</CondicionVenta>')
    sb.append('<PlazoCredito>' + str(plazo_credito) + '</PlazoCredito>')
    if lines:
        sb.append('<DetalleServicio>')

        for (k, v) in lines.items():
            numero_linea = numero_linea + 1

            sb.append('<LineaDetalle>')
            sb.append('<NumeroLinea>' + str(numero_linea) + '</NumeroLinea>')

            if inv.tipo_documento == 'FEE' and v.get('partidaArancelaria'):
                sb.append('<PartidaArancelaria>' + str(v['partidaArancelaria']) + '</PartidaArancelaria>')

            if v.get('codigoCabys'):
                cabys_code = str(v["codigoCabys"])
                if len(cabys_code) != 13:
                    # Algunos cabys no traen 13 digitos, por lo que no estan generando la factura correcta
                    # las siguientes dos lineas son un fix temporal para pruebas
                    # cabys_code = str(v["codigoCabys"]).zfill(13)
                    # sb.append("<CodigoCABYS>" + cabys_code + "</CodigoCABYS>")
                    raise UserError(
                        _(
                            'El código CABYS "%s" en la línea %s no es válido. '
                            "Debe tener exactamente 13 dígitos."
                        )
                        % (cabys_code, numero_linea)
                    )

                sb.append("<CodigoCABYS>" + cabys_code + "</CodigoCABYS>")

            if v.get('codigo'):
                sb.append('<CodigoComercial>')
                sb.append('<Tipo>04</Tipo>')
                sb.append('<Codigo>' + str(v['codigo']) + '</Codigo>')
                sb.append('</CodigoComercial>')

            sb.append('<Cantidad>' + str(v['cantidad']) + '</Cantidad>')
            sb.append('<UnidadMedida>' + str(v['unidadMedida']) + '</UnidadMedida>')
            sb.append('<Detalle>' + str(v['detalle']) + '</Detalle>')
            sb.append('<PrecioUnitario>' + str(v['precioUnitario']) + '</PrecioUnitario>')
            sb.append('<MontoTotal>' + str(v['montoTotal']) + '</MontoTotal>')
            if v.get('montoDescuento'):
                sb.append('<Descuento>')
                sb.append('<MontoDescuento>' + str(v['montoDescuento']) + '</MontoDescuento>')
                sb.append('<CodigoDescuento>' + str(v['codigoDescuento']) + '</CodigoDescuento>')
                if v.get('codigoDescuento') == '99':
                    sb.append('<CodigoDescuentoOTRO>' + str(v['codigoDescuentoOTRO']) + '</CodigoDescuentoOTRO>')
                if v.get('naturalezaDescuento'):    
                    sb.append('<NaturalezaDescuento>' + str(v['naturalezaDescuento']) + '</NaturalezaDescuento>')
                sb.append('</Descuento>')

            sb.append('<SubTotal>' + str(v['subtotal']) + '</SubTotal>')

            if inv.tipo_documento not in ['FEE', 'REP']:
                sb.append('<BaseImponible>' + str(v['subtotal']) + '</BaseImponible>')

                # En caso que el impuesto sea: selectivo de consumo (02),
                # entonces BaseImponible se obtiene de la suma entre el campo “Subtotal”, más el impuesto selectivo de consumo (02)
                # o el impuesto al cemento (12)
                if v['impuesto'][1]['codigo']=='02' or v['impuesto'][1]['codigo']=='12':
                    sum_baseImponible = v['subtotal'] + v['impuesto'][1]['monto']
                    sb.append('<BaseImponible>' + str(sum_baseImponible) + '</BaseImponible>')

            if v.get('impuesto'):
                for (a, b) in v['impuesto'].items():
                    sb.append('<Impuesto>')
                    sb.append('<Codigo>' + str(b['codigo']) + '</Codigo>')
                    if str(b['iva_tax_code']).isdigit():
                        sb.append('<CodigoTarifaIVA>' + str(b['iva_tax_code']) + '</CodigoTarifaIVA>')
                    sb.append('<Tarifa>' + str(b['tarifa']) + '</Tarifa>')
                    if 'taxRegalia' in v:
                        sb.append('<Monto>' + str(v['taxRegalia']) + '</Monto>')
                    else:
                        sb.append('<Monto>' + str(b['monto']) + '</Monto>')

                    if inv.tipo_documento != 'FEE':
                        if b.get('exoneracion'):
                            sb.append('<Exoneracion>')

                            sb.append('<TipoDocumento>' +
                                      str(receiver_company.type_exoneration.code) +
                                      '</TipoDocumento>')
                            sb.append('<NumeroDocumento>' +
                                      str(receiver_company.exoneration_number) +
                                      '</NumeroDocumento>')
                            sb.append('<NombreInstitucion>' +
                                      str(receiver_company.institution_name) +
                                      '</NombreInstitucion>')
                            sb.append('<FechaEmision>' +
                                      str(receiver_company.date_issue) + 'T00:00:00-06:00' +
                                      '</FechaEmision>')
                            sb.append('<PorcentajeExoneracion>' +
                                      str(b['exoneracion']['porcentajeCompra']) +
                                      '</PorcentajeExoneracion>')
                            sb.append('<MontoExoneracion>' +
                                      str(b['exoneracion']['montoImpuesto']) +
                                      '</MontoExoneracion>')

                            sb.append('</Exoneracion>')
                    sb.append('</Impuesto>')

                if inv.tipo_documento not in ['FEE','FEC','REP']:
                    if 'taxRegalia' in v:
                        sb.append('<ImpuestoAsumidoEmisorFabrica>' + str(v['taxRegalia']) + '</ImpuestoAsumidoEmisorFabrica>')
                        sb.append('<ImpuestoNeto>' + str(0) + '</ImpuestoNeto>')
                    elif inv.tipo_documento != 'FEE':
                        sb.append('<ImpuestoAsumidoEmisorFabrica>' + str(0) + '</ImpuestoAsumidoEmisorFabrica>')
                        sb.append('<ImpuestoNeto>' + str(v['impuestoNeto']) + '</ImpuestoNeto>')
                
            sb.append('<MontoTotalLinea>' + str(round(v['montoTotalLinea'],5)) + '</MontoTotalLinea>')
            sb.append('</LineaDetalle>')
        sb.append('</DetalleServicio>')

    if otrosCargos:
        sb.append('<OtrosCargos>')
        for otro_cargo in otrosCargos:
            sb.append('<TipoDocumento>' + str(otrosCargos[otro_cargo]['TipoDocumento']) + '</TipoDocumento>')

            if otrosCargos[otro_cargo].get('NumeroIdentidadTercero'):
                sb.append('<NumeroIdentidadTercero>' +
                          str(otrosCargos[otro_cargo]['NumeroIdentidadTercero']) +
                          '</NumeroIdentidadTercero>')

            if otrosCargos[otro_cargo].get('NombreTercero'):
                sb.append('<NombreTercero>' + str(otrosCargos[otro_cargo]['NombreTercero']) + '</NombreTercero>')

            sb.append('<Detalle>' + str(otrosCargos[otro_cargo]['Detalle']) + '</Detalle>')

            if otrosCargos[otro_cargo].get('Porcentaje'):
                sb.append('<Porcentaje>' + str(otrosCargos[otro_cargo]['Porcentaje']) + '</Porcentaje>')

            sb.append('<MontoCargo>' + str(otrosCargos[otro_cargo]['MontoCargo']) + '</MontoCargo>')
        sb.append('</OtrosCargos>')

    sb.append('<ResumenFactura>')
    sb.append('<CodigoTipoMoneda>')
    sb.append('<CodigoMoneda>' + str(cod_moneda) + '</CodigoMoneda>')
    sb.append('<TipoCambio>' + str(currency_rate) + '</TipoCambio>')
    sb.append('</CodigoTipoMoneda>')

    sb.append('<TotalServGravados>' + str(total_servicio_gravado) + '</TotalServGravados>')
    sb.append('<TotalServExentos>' + str(total_servicio_exento) + '</TotalServExentos>')

    if inv.tipo_documento != 'FEE':
        sb.append('<TotalServExonerado>' + str(totalServExonerado) + '</TotalServExonerado>')
        sb.append('<TotalServNoSujeto>' + str(total_servicio_no_sujeto) + '</TotalServNoSujeto>')
        

    sb.append('<TotalMercanciasGravadas>' + str(total_mercaderia_gravado) + '</TotalMercanciasGravadas>')
    sb.append('<TotalMercanciasExentas>' + str(total_mercaderia_exento) + '</TotalMercanciasExentas>')

    if inv.tipo_documento != 'FEE':
        sb.append('<TotalMercExonerada>' + str(totalMercExonerada) + '</TotalMercExonerada>')
        sb.append('<TotalMercNoSujeta>' + str(total_mercaderia_no_sujeto) + '</TotalMercNoSujeta>')

    sb.append('<TotalGravado>' + str(round(total_servicio_gravado + total_mercaderia_gravado, 5)) + '</TotalGravado>')
    sb.append('<TotalExento>' + str(round(total_servicio_exento + total_mercaderia_exento, 5)) + '</TotalExento>')

    if inv.tipo_documento != 'FEE':
        sb.append('<TotalExonerado>' + str(round(totalServExonerado + totalMercExonerada, 5)) + '</TotalExonerado>')
        sb.append('<TotalNoSujeto>' + str(round(total_servicio_no_sujeto + total_mercaderia_no_sujeto, 5)) + '</TotalNoSujeto>')

    sb.append('<TotalVenta>' +
              str(round(total_servicio_gravado +
                        total_mercaderia_gravado +
                        total_servicio_exento +
                        total_mercaderia_exento +
                        totalServExonerado +
                        totalMercExonerada, 5)) +
              '</TotalVenta>')
    sb.append('<TotalDescuentos>' + str(round(total_descuento, 5)) + '</TotalDescuentos>')
    sb.append('<TotalVentaNeta>' + str(round(base_total, 5)) + '</TotalVentaNeta>')

    for tax_code in total_desgloce_impuesto:
        for iva_tax in total_desgloce_impuesto[tax_code]:
            sb.append('<TotalDesgloseImpuesto>') 
            sb.append('<Codigo>' + str(tax_code) + '</Codigo>')
            sb.append('<CodigoTarifaIVA>' + str(iva_tax) + '</CodigoTarifaIVA>')
            sb.append('<TotalMontoImpuesto>' + str(round(total_desgloce_impuesto[tax_code][iva_tax], 5)) + '</TotalMontoImpuesto>')
            sb.append('</TotalDesgloseImpuesto>')

    sb.append('<TotalImpuesto>' + str(round(total_impuestos, 5)) + '</TotalImpuesto>')
    if total_impuestos_asum_emisor_fabrica > 0:
        sb.append('<TotalImpAsumEmisorFabrica>' + str(round(total_impuestos_asum_emisor_fabrica, 5)) + '</TotalImpAsumEmisorFabrica>')

    if total_iva_devuelto:
        sb.append('<TotalIVADevuelto>' + str(round(total_iva_devuelto, 5)) + '</TotalIVADevuelto>')

    sb.append('<TotalOtrosCargos>' + str(totalOtrosCargos) + '</TotalOtrosCargos>')
    sb.append('<MedioPago>')

    payment_method_length = len(payment_methods_id)
    total_payment_method = round(base_total + total_impuestos + totalOtrosCargos - total_iva_devuelto, 5)
    for payment_method_counter in range(min(payment_method_length, 4)):
        sb.append('<TipoMedioPago>' + payment_methods_id[payment_method_counter] + '</TipoMedioPago>')
        sb.append('<TotalMedioPago>' + str(total_payment_method)+ '</TotalMedioPago>')

    sb.append('</MedioPago>')

    sb.append('<TotalComprobante>' +
              str(round(base_total + total_impuestos + totalOtrosCargos - total_iva_devuelto, 5)) +
              '</TotalComprobante>')

    sb.append('</ResumenFactura>')

    if tipo_documento_referencia:
        sb.append('<InformacionReferencia>')
        sb.append('<TipoDocIR>' + str(tipo_documento_referencia) + '</TipoDocIR>')
        if numero_documento_referencia and fecha_emision_referencia:
            sb.append('<Numero>' + str(numero_documento_referencia) + '</Numero>')
            sb.append('<FechaEmisionIR>' + str(fecha_emision_referencia) + '</FechaEmisionIR>')
        if codigo_referencia:   
            sb.append('<Codigo>' + str(codigo_referencia) + '</Codigo>')
        if razon_referencia:   
            sb.append('<Razon>' + str(razon_referencia) + '</Razon>')
        sb.append('</InformacionReferencia>')
    purchase_order = (getattr(inv, "customer_purchase_order", False) or "").strip()
    if invoice_comments or invoice_ref or purchase_order:
        sb.append('<Otros>')
        if invoice_comments:
            sb.append('<OtroTexto>' + str(invoice_comments) + '</OtroTexto>')
        if invoice_ref:
            sb.append('<OtroContenido>' + escape(str(invoice_ref)) + '</OtroContenido>')
        if purchase_order:
            sb.append('<OtroTexto>Orden de compra: ' + escape(purchase_order) + '</OtroTexto>')
        sb.append('</Otros>')

    sb.append('</' + fe_enums.tagName[inv.tipo_documento] + '>')

    return sb


def gen_xml_rep_v44(
    payment, number_electronic, date_issuance, lines, tax_breakdown, totals
):
    """
    Generate REP (Recibo Electrónico de Pago) XML document.

    Args:
        payment: account.payment record
        number_electronic: 50-character electronic key (Clave)
        date_issuance: ISO datetime string (e.g., "2024-01-15T10:30:00-06:00")
        lines: dict of line data from _calculate_rep_proration
        tax_breakdown: dict (reserved for future use)
        totals: dict with total values

    Returns:
        StringBuilder object containing the XML
    """
    # Decimal helpers for XML serialization - eliminates floating-point drift
    PRECISION_5_DECIMALS = Decimal("0.00001")
    PRECISION_2_DECIMALS = Decimal("0.01")

    def to_decimal(value):
        """Convert any numeric value to Decimal safely."""
        return Decimal(str(value or 0))

    def format_amount(value):
        """Format monetary amount with 5 decimal places (fixed notation)."""
        return format(
            to_decimal(value).quantize(PRECISION_5_DECIMALS, rounding=ROUND_HALF_UP),
            "f",
        )

    def format_rate(value):
        """Format percentage/tariff with 2 decimal places (fixed notation)."""
        return format(
            to_decimal(value).quantize(PRECISION_2_DECIMALS, rounding=ROUND_HALF_UP),
            "f",
        )

    def get_codigo_tarifa_iva(tax_rate):
        """Map tax rate percentage to CodigoTarifaIVA."""
        rate_integer = int(
            to_decimal(tax_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        iva_code_mapping = {
            0: "01",
            1: "02",
            2: "03",
            4: "04",
            8: "07",
            13: "08",
        }
        return iva_code_mapping.get(rate_integer, "08")  # Default to 08 (13%)

    # Issuer = Company (the one receiving the payment)
    issuing_company = payment.company_id
    # Receiver = Partner (the one making the payment)
    receiver_company = payment.partner_id
    issuing_company_name = issuing_company.legal_name or issuing_company.name

    # Extract consecutive number from electronic key (positions 21-41)
    numero_consecutivo = (
        number_electronic[21:41] if len(number_electronic) >= 41 else ""
    )

    sb = StringBuilder()
    sb.append(
        "<"
        + fe_enums.tagName["REP"]
        + ' xmlns="'
        + fe_enums.XmlnsHacienda["REP"]
        + '" '
    )
    sb.append(
        'xmlns:ds="http://www.w3.org/2000/09/xmldsig#" xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
    )
    sb.append('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ')
    sb.append('xsi:schemaLocation="' + fe_enums.schemaLocation["REP"] + '">')

    # Clave (50-character electronic key)
    sb.append("<Clave>" + number_electronic + "</Clave>")

    sb.append(
        "<ProveedorSistemas>"
        + (
            issuing_company.invoice_provider_identification
            if issuing_company.invoice_provider_type == "external"
            else issuing_company.vat
        )
        + "</ProveedorSistemas>"
    )

    sb.append("<NumeroConsecutivo>" + numero_consecutivo + "</NumeroConsecutivo>")
    sb.append("<FechaEmision>" + date_issuance + "</FechaEmision>")

    # EMISOR (Company receiving payment)
    sb.append("<Emisor>")
    sb.append("<Nombre>" + escape(issuing_company_name) + "</Nombre>")
    sb.append("<Identificacion>")
    sb.append("<Tipo>" + str(issuing_company.identification_id.code) + "</Tipo>")
    sb.append("<Numero>" + str(issuing_company.vat) + "</Numero>")
    sb.append("</Identificacion>")

    # CorreoElectronico is mandatory/optional but valid here
    sb.append(
        "<CorreoElectronico>" + str(issuing_company.email) + "</CorreoElectronico>"
    )
    sb.append("</Emisor>")

    # RECEPTOR (Customer making payment)
    vat = re.sub("[^0-9]", "", receiver_company.vat or "")
    if not receiver_company.identification_id:
        if len(vat) == 9:
            id_code = "01"  # Cedula Fisica
        elif len(vat) == 10:
            id_code = "02"  # Cedula Juridica
        elif len(vat) in (11, 12):
            id_code = "03"  # DIMEX
        else:
            id_code = "05"  # Extranjero
    else:
        id_code = receiver_company.identification_id.code

    sb.append("<Receptor>")
    sb.append("<Nombre>" + escape(str(receiver_company.name[:99])) + "</Nombre>")
    sb.append("<Identificacion>")
    sb.append("<Tipo>" + str(id_code) + "</Tipo>")
    sb.append("<Numero>" + str(vat) + "</Numero>")
    sb.append("</Identificacion>")

    # Email for receptor (optional)
    re_match = r"^(\s?[^\s,]+@[^\s,]+\.[^\s,]+\s?,)*(\s?[^\s,]+@[^\s,]+\.[^\s,]+)$"
    match = receiver_company.email and re.match(
        re_match, receiver_company.email.lower()
    )
    if match:
        sb.append(
            "<CorreoElectronico>" + str(receiver_company.email) + "</CorreoElectronico>"
        )
    sb.append("</Receptor>")

    # CondicionVenta - Must be '09' or '11' per XSD V4.4 for REP
    # Strict mapping from invoice context. No defaults allowed.
    # 09 = Pago del servicios prestado al Estado (Matches Invoice 08)
    # 11 = Pago de venta a crédito en IVA hasta 90 días (Matches Invoice 02 - Standard Credit)

    rep_condition = False

    # Try to get from source invoice
    source_inv = False
    if hasattr(payment, "rep_bak_invoice_id") and payment.rep_bak_invoice_id:
        source_inv = payment.rep_bak_invoice_id
    elif hasattr(payment, "reconciled_invoice_ids") and payment.reconciled_invoice_ids:
        source_inv = payment.reconciled_invoice_ids[0]

    if source_inv and source_inv.invoice_payment_term_id:
        sale_code = source_inv.invoice_payment_term_id.sale_conditions_id.code
        # Invoice 08 -> REP 09
        if sale_code == "08":
            rep_condition = "09"
        # Invoice 02 -> REP 11
        elif sale_code == "02":
            rep_condition = "11"
        else:
            # REP restriction: Only 02 and 08 are allowed to generate REP as per business rules
            # and only 09/11 are valid in XSD.
            raise ValueError(
                "Invalid Sale Condition for REP: %s. Expected '02' or '08'." % sale_code
            )
    else:
        # Fallback if no invoice context (should not happen due to validation)
        # But per user request: "Do not infer... and do not default to 11".
        # We must fail if we can't determine it.
        raise ValueError(
            "Cannot determine Sale Condition for REP. Source invoice not found."
        )

    sb.append("<CondicionVenta>" + rep_condition + "</CondicionVenta>")

    # DetalleServicio
    sb.append("<DetalleServicio>")
    for line_num, line_data in lines.items():
        sb.append("<LineaDetalle>")
        sb.append("<NumeroLinea>" + str(line_num) + "</NumeroLinea>")

        # Detalle (description)
        detalle = escape(str(line_data.get("detalle", "Pago de factura"))[:160])
        sb.append("<Detalle>" + detalle + "</Detalle>")

        # MontoTotal (base amount before taxes)
        line_monto_total = to_decimal(line_data.get("montoTotal", 0))
        sb.append("<MontoTotal>" + format_amount(line_monto_total) + "</MontoTotal>")

        # SubTotal (same as MontoTotal for REP since no discounts)
        line_subtotal = to_decimal(line_data.get("subtotal", line_monto_total))
        sb.append("<SubTotal>" + format_amount(line_subtotal) + "</SubTotal>")

        # Impuesto (Taxes)
        impuestos = line_data.get("impuesto", {})
        if impuestos:
            for tax_key, tax_data in impuestos.items():
                sb.append("<Impuesto>")
                codigo = str(tax_data.get("codigo", "01"))
                sb.append("<Codigo>" + codigo + "</Codigo>")

                # CodigoTarifaIVA - REQUIRED for Tax 01 (IVA)
                tax_tarifa = to_decimal(tax_data.get("tarifa", 0))

                if codigo == "01":
                    rep_iva_code = get_codigo_tarifa_iva(tax_tarifa)
                    sb.append("<CodigoTarifaIVA>" + rep_iva_code + "</CodigoTarifaIVA>")

                sb.append("<Tarifa>" + format_rate(tax_tarifa) + "</Tarifa>")
                sb.append("<Monto>" + format_amount(tax_data.get("monto", 0)) + "</Monto>")
                sb.append("</Impuesto>")

        # ImpuestoNeto (net tax for this line)
        line_impuesto_neto = to_decimal(line_data.get("impuestoNeto", 0))
        sb.append("<ImpuestoNeto>" + format_amount(line_impuesto_neto) + "</ImpuestoNeto>")

        # MontoTotalLinea (line total including tax)
        line_monto_total_linea = to_decimal(line_data.get("montoTotalLinea", line_subtotal + line_impuesto_neto))
        sb.append("<MontoTotalLinea>"+ format_amount(line_monto_total_linea) + "</MontoTotalLinea>")

        sb.append("</LineaDetalle>")
    sb.append("</DetalleServicio>")

    # ResumenFactura
    sb.append("<ResumenFactura>")

    # CodigoTipoMoneda
    sb.append("<CodigoTipoMoneda>")
    currency_name = str(payment.currency_id.name) if payment.currency_id else "CRC"
    sb.append("<CodigoMoneda>" + currency_name + "</CodigoMoneda>")

    # TipoCambio - Get exchange rate
    exchange_rate = Decimal("1.00000")
    if currency_name != "CRC":
        # Try to get exchange rate from context or calculate
        # For non-CRC currencies, we need the rate to CRC
        try:
            if payment.company_id.currency_id.name == "CRC":
                # Payment is in foreign currency, company is in CRC
                if payment.currency_id.rate:
                    exchange_rate = (
                        Decimal("1") / to_decimal(payment.currency_id.rate)
                    ).quantize(PRECISION_5_DECIMALS, rounding=ROUND_HALF_UP)
        except Exception:
            exchange_rate = Decimal("1.00000")
    sb.append("<TipoCambio>" + format_amount(exchange_rate) + "</TipoCambio>")
    sb.append("</CodigoTipoMoneda>")

    # Totals - use Decimal throughout
    summary_total_venta = to_decimal(totals.get("total_venta", 0))
    summary_total_venta_neta = to_decimal(
        totals.get("total_venta_neta", summary_total_venta)
    )
    summary_total_impuesto = to_decimal(totals.get("total_tax", 0))
    summary_total_comprobante = to_decimal(
        totals.get(
            "total_comprobante", summary_total_venta_neta + summary_total_impuesto
        )
    )

    sb.append("<TotalVenta>" + format_amount(summary_total_venta) + "</TotalVenta>")
    sb.append(
        "<TotalVentaNeta>"
        + format_amount(summary_total_venta_neta)
        + "</TotalVentaNeta>"
    )

    # TotalDesgloseImpuesto - Required when taxes are present
    # For IVA (codigo 01), CodigoTarifaIVA is mandatory
    # Aggregate taxes by (codigo, iva_code) for the breakdown using Decimal

    tax_breakdown_aggregated = {}  # {(codigo, iva_code): Decimal monto_total}
    for line_num, line_data in lines.items():
        impuestos = line_data.get("impuesto", {})
        for tax_key, tax_data in impuestos.items():
            codigo = str(tax_data.get("codigo", "01"))
            tarifa = to_decimal(tax_data.get("tarifa", 0))
            monto = to_decimal(tax_data.get("monto", 0))

            # For codigo 01 (IVA), use the CodigoTarifaIVA as part of the key
            if codigo == "01":
                iva_code = get_codigo_tarifa_iva(tarifa)
                breakdown_key = (codigo, iva_code)
            else:
                breakdown_key = (codigo, None)

            if breakdown_key not in tax_breakdown_aggregated:
                tax_breakdown_aggregated[breakdown_key] = Decimal("0")
            tax_breakdown_aggregated[breakdown_key] += monto

    for (codigo, iva_code), aggregated_tax_amount in tax_breakdown_aggregated.items():
        if aggregated_tax_amount > 0:
            sb.append("<TotalDesgloseImpuesto>")
            sb.append("<Codigo>" + codigo + "</Codigo>")

            # CodigoTarifaIVA is mandatory for IVA (codigo 01)
            if codigo == "01" and iva_code:
                sb.append("<CodigoTarifaIVA>" + iva_code + "</CodigoTarifaIVA>")

            sb.append("<TotalMontoImpuesto>" + round(aggregated_tax_amount, 5) + "</TotalMontoImpuesto>" )
            sb.append("</TotalDesgloseImpuesto>")

    sb.append("<TotalImpuesto>" + round(summary_total_impuesto, 5) + "</TotalImpuesto>")

    # MedioPago (Payment Method)
    sb.append("<MedioPago>")

    # Map journal type to Hacienda payment method code
    # 01 = Efectivo, 02 = Tarjeta, 03 = Cheque, 04 = Transferencia, 99 = Otros
    method_code = "99"
    if payment.journal_id.type == "cash":
        method_code = "01"
    elif payment.journal_id.type == "bank":
        # Check if it's a card or transfer - default to transfer for bank journals
        method_code = "04"

    sb.append("<TipoMedioPago>" + method_code + "</TipoMedioPago>")
    sb.append(
        "<TotalMedioPago>"
        + format_amount(summary_total_comprobante)
        + "</TotalMedioPago>"
    )
    sb.append("</MedioPago>")

    sb.append(
        "<TotalComprobante>"
        + format_amount(summary_total_comprobante)
        + "</TotalComprobante>"
    )
    sb.append("</ResumenFactura>")

    # InformacionReferencia - Reference to the paid invoice(s)
    # Get invoices from payment's rep_bak_invoice_id or rep_all_invoice_ids
    referenced_invoices = payment.env["account.move"]

    # Try rep_all_invoice_ids first (many2many for multi-invoice payments)
    if hasattr(payment, "rep_all_invoice_ids") and payment.rep_all_invoice_ids:
        referenced_invoices = payment.rep_all_invoice_ids
    # Fall back to rep_bak_invoice_id (single invoice backup)
    elif hasattr(payment, "rep_bak_invoice_id") and payment.rep_bak_invoice_id:
        referenced_invoices = payment.rep_bak_invoice_id
    # Last resort: try reconciled invoices (might be empty before posting)
    else:
        referenced_invoices = payment.reconciled_invoice_ids

    for inv in referenced_invoices:
        if inv.number_electronic and len(inv.number_electronic) == 50:
            sb.append("<InformacionReferencia>")

            # TipoDocIR - Document type being referenced
            # 01=FE, 02=ND, 03=NC, 04=TE, 05=REP, etc.
            tipo_doc_ref = "01"  # Default to FE (Factura Electrónica)
            if inv.tipo_documento == "FE":
                tipo_doc_ref = "01"
            elif inv.tipo_documento == "ND":
                tipo_doc_ref = "02"
            elif inv.tipo_documento == "NC":
                tipo_doc_ref = "03"
            elif inv.tipo_documento == "TE":
                tipo_doc_ref = "04"
            elif inv.tipo_documento == "FEE":
                tipo_doc_ref = "09"

            sb.append("<TipoDocIR>" + tipo_doc_ref + "</TipoDocIR>")
            sb.append("<Numero>" + inv.number_electronic + "</Numero>")
            sb.append("<FechaEmisionIR>" + str(inv.date_issuance) + "</FechaEmisionIR>")

            # Codigo - Reference reason code
            # For REP, we use '99' (Otros) since we're documenting a payment, not correcting/canceling
            sb.append("<Codigo>99</Codigo>")
            sb.append("<CodigoReferenciaOTRO>Pago de Factura</CodigoReferenciaOTRO>")
            sb.append(
                "<Razon>Pago correspondiente a factura "
                + str(inv.name or inv.number_electronic[:20])
                + "</Razon>"
            )
            sb.append("</InformacionReferencia>")

    sb.append("</" + fe_enums.tagName["REP"] + ">")

    return sb


# Funcion para enviar el XML al Ministerio de Hacienda
def send_xml_fe(inv, token, date, xml, tipo_ambiente):
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-type': 'application/json'
    }

    # establecer el ambiente al cual me voy a conectar
    endpoint = fe_enums.UrlHaciendaRecepcion[tipo_ambiente]

    xml_base64 = string_to_base64(xml)

    data = {
        'clave': inv.number_electronic,
        'fecha': date,
        'emisor': {
            'tipoIdentificacion': inv.company_id.identification_id.code,
            'numeroIdentificacion': inv.company_id.vat
        },
        'comprobanteXml': xml_base64
    }
    if inv.partner_id and inv.partner_id.vat:
        if not inv.partner_id.identification_id:
            if len(inv.partner_id.vat) == 9:  # cedula fisica
                id_code = '01'
            elif len(inv.partner_id.vat) == 10:  # cedula juridica
                id_code = '02'
            elif len(inv.partner_id.vat) == 11 or len(inv.partner_id.vat) == 12:  # dimex
                id_code = '03'
            else:
                id_code = '05'
        else:
            id_code = inv.partner_id.identification_id.code

        data['receptor'] = {'tipoIdentificacion': id_code,
                            'numeroIdentificacion': inv.partner_id.vat}

    json_hacienda = json.dumps(data)

    try:
        # enviando solicitud post y guardando la respuesta como un objeto json
        response = requests.request("POST", endpoint, data=json_hacienda, headers=headers)

        # Verificamos el codigo devuelto, si es distinto de 202 es porque hacienda nos está devolviendo algun error
        if response.status_code != 202:
            error_caused_by = response.headers.get(
                'X-Error-Cause') if 'X-Error-Cause' in response.headers else ''
            error_caused_by += response.headers.get('validation-exception', '')
            _logger.error('Status: {}, Text {}'.format(
                response.status_code, error_caused_by))

            return {
                'status': response.status_code,
                'text': error_caused_by
            }
        else:
            # respuesta_hacienda = response.status_code
            return {
                'status': response.status_code,
                'text': response.reason
            }
            # return respuesta_hacienda

    except ImportError:
        raise Warning(_('Error enviando el XML al Ministerior de Hacienda'))

def schema_validator(xml_file, xsd_file) -> bool:
    """ verifies a xml
    :param xml_invoice: Invoice xml
    :param  xsd_file: XSD File Name
    :return:
    """

    xmlschema = etree.XMLSchema(etree.parse(os.path.join(os.path.dirname(__file__), "xsd/" + xsd_file)))

    xml_doc = base64decode(xml_file)
    root = etree.fromstring(xml_doc, etree.XMLParser(remove_blank_text=True))
    result = xmlschema.validate(root)

    return result

# Obtener Attachments para las Facturas Electrónicas
def get_invoice_attachments(invoice, record_id):
    attachments = []

    domain = [
        ('res_model', '=', invoice._name),
        ('res_id', '=', invoice.id),
        ('res_field', '=', 'xml_comprobante')
    ]
    attachment = invoice.env['ir.attachment'].sudo().search(domain, limit=1)

    if attachment.id:
        # attachment.name = invoice.fname_xml_comprobante
        # attachment.datas_fname = invoice.fname_xml_comprobante
        attach_copy = invoice.env['ir.attachment'].create(
            {
                'name': invoice.fname_xml_comprobante,
                'type': 'binary',
                'datas': invoice.xml_comprobante,
                'res_name': invoice.fname_xml_comprobante,
                'mimetype': 'text/xml'
            }
        )
        attachments.append(attach_copy.id)

    domain_resp = [
        ('res_model', '=', invoice._name),
        ('res_id', '=', invoice.id),
        ('res_field', '=', 'xml_respuesta_tributacion')
    ]
    attachment_resp = invoice.env['ir.attachment'].sudo().search(domain_resp, limit=1)

    if attachment_resp.id:
        attach_resp_copy = invoice.env['ir.attachment'].create(
            {
                'name': invoice.fname_xml_respuesta_tributacion,
                'type': 'binary',
                'datas': invoice.xml_respuesta_tributacion,
                'res_name': invoice.fname_xml_respuesta_tributacion,
                'mimetype': 'text/xml'
            }
        )
        attachments.append(attach_resp_copy.id)

    return attachments

def parse_xml(name):
    return etree.parse(name)

# CONVIERTE UN STRING A BASE 64
def string_to_base64(s):
    return base64.b64encode(s).decode()

# TOMA UNA CADENA Y ELIMINA LOS CARACTERES AL INICIO Y AL FINAL
def string_strip(s, start, end):
    return s[start:-end]

# Tomamos el XML y le hacemos el decode de base 64, esto por ahora es solo para probar
# la posible implementacion de la firma en python
def base64decode(string_decode):
    return base64.b64decode(string_decode)

# TOMA UNA CADENA EN BASE64 Y LA DECODIFICA PARA ELIMINAR EL b' Y DEJAR EL STRING CODIFICADO
# DE OTRA MANERA HACIENDA LO RECHAZA
def base64_utf8_decoder(s):
    return s.decode("utf-8")

# CLASE PERSONALIZADA (NO EXISTE EN PYTHON) QUE CONSTRUYE UNA CADENA MEDIANTE APPEND SEMEJANTE
# AL STRINGBUILDER DEL C#
class StringBuilder:
    _file_str = None

    def __init__(self):
        self._file_str = io.StringIO()

    def append(self, str):
        self._file_str.write(str)

    def __str__(self):
        return self._file_str.getvalue()

def consulta_clave(clave, token, tipo_ambiente):
    endpoint = fe_enums.UrlHaciendaRecepcion[tipo_ambiente] + clave

    headers = {
        'Authorization': 'Bearer {}'.format(token),
        'Cache-Control': 'no-cache',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    _logger.debug('FECR - consulta_clave - url: %s', endpoint)

    try:
        # response = requests.request("GET", url, headers=headers)
        response = requests.get(endpoint, headers=headers)

    except requests.exceptions.RequestException as e:
        _logger.error('Exception %s', e)
        return {'status': -1, 'text': 'Excepcion %s' % e}

    if 200 <= response.status_code <= 299:
        response_json = {
            'status': 200,
            'ind-estado': response.json().get('ind-estado'),
            'respuesta-xml': response.json().get('respuesta-xml')
        }
    elif 400 <= response.status_code <= 499:
        _logger.error('FECR - 400 - consulta_clave failed.  error: %s reason: %s', response.status_code, response.reason)
        response_json = {
            'status': 400,
            'ind-estado': 'error'
        }
    else:
        _logger.error('FECR - consulta_clave failed.  error: %s', response.status_code)
        response_json = {
            'status': response.status_code,
            'text': 'token_hacienda failed: %s' % response.reason
        }
    return response_json

def get_economic_activities(company):
    hmapi = company.env['ir.config_parameter'].sudo().get_param('url_base')
    endpoint = hmapi + "identificacion=" + company.vat

    headers = {
        'Cache-Control': 'no-cache',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    try:
        response = requests.get(endpoint, headers=headers)
    except requests.exceptions.RequestException as e:
        _logger.error('Exception %s', e)
        return {'status': -1, 'text': 'Excepcion %s' % e}

    if 200 <= response.status_code <= 299:
        _logger.debug('FECR - get_economic_activities response: %s', (response.json()))
        response_json = {
            'status': 200,
            'activities': response.json().get('actividades'),
            'name': response.json().get('nombre'),
            'situacion': response.json().get('situacion', {}).get('estado')
        }
    # elif 400 <= response.status_code <= 499:
    #    response_json = {'status': 400, 'ind-estado': 'error'}
    else:
        _logger.error('FECR - get_economic_activities failed.  error: %s', response.status_code)
        response_json = {
            'status': response.status_code,
            'text': 'get_economic_activities failed: %s' % response.reason
        }
    return response_json

def consulta_documentos(self, inv, env, token_m_h, date_cr, xml_firmado):
    if (inv.move_type in ['in_invoice', 'in_refund']) and (inv.tipo_documento != 'FEC'):
        clave = inv.number_electronic + "-" + inv.consecutive_number_receiver
    else:
        clave = inv.number_electronic

    response_json = consulta_clave(clave, token_m_h, env)
    _logger.debug(response_json)
    estado_m_h = response_json.get('ind-estado')

    # Siempre sin importar el estado se actualiza la fecha de acuerdo a la devuelta por Hacienda y
    # se carga el xml devuelto por Hacienda
    last_state = inv.state_tributacion
    inv.state_tributacion = estado_m_h
    if inv.move_type in ['out_invoice', 'out_refund']:
        # Se actualiza el estado con el que devuelve Hacienda
        last_state = inv.state_tributacion
        inv.state_tributacion = estado_m_h
        if date_cr:
            inv.date_issuance = date_cr
        if xml_firmado:
            inv.fname_xml_comprobante = inv.tipo_documento + inv.number_electronic + '.xml'

            # inv.xml_comprobante = xml_firmado
            self.env['ir.attachment'].sudo().create(
                {
                    'name': inv.fname_xml_comprobante,
                    'type': 'binary',
                    'datas': xml_firmado,
                    'res_model': self._name,
                    'res_id': inv.id,
                    'res_field': 'xml_comprobante',
                    'res_name': inv.fname_xml_comprobante,
                    'mimetype': 'text/xml'
                }
            )
    elif inv.move_type in ['in_invoice', 'in_refund']:
        if xml_firmado:
            inv.fname_xml_comprobante = 'AHC_' + inv.number_electronic + '.xml'

            # inv.xml_comprobante = xml_firmado
            self.env['ir.attachment'].sudo().create(
                {
                    'name': inv.fname_xml_comprobante,
                    'type': 'binary',
                    'datas': xml_firmado,
                    'res_model': self._name,
                    'res_id': inv.id,
                    'res_field': 'xml_comprobante',
                    'res_name': inv.fname_xml_comprobante,
                    'mimetype': 'text/xml'
                }
            )

    # Si fue aceptado o rechazado por haciendo se carga la respuesta
    if (estado_m_h in ['aceptado', 'rechazado']) or (inv.move_type in ['out_invoice', 'out_refund']):
        inv.fname_xml_respuesta_tributacion = 'AHC_' + inv.number_electronic + '.xml'

        # inv.xml_respuesta_tributacion = response_json.get('respuesta-xml')
        self.env['ir.attachment'].create(
            {
                'name': inv.fname_xml_respuesta_tributacion,
                'type': 'binary',
                'datas': response_json.get('respuesta-xml'),
                'res_model': inv._name,
                'res_id': inv.id,
                'res_field': 'xml_respuesta_tributacion',
                'res_name': inv.fname_xml_respuesta_tributacion,
                'mimetype': 'text/xml'
            }
        )

    # Si fue aceptado por Hacienda y es un factura de cliente o nota de crédito, se envía el correo con los documentos
    if inv.tipo_documento != 'FEC' and estado_m_h == 'aceptado' and (not last_state or last_state == 'procesando'):
        # if not inv.partner_id.opt_out:
        if inv.move_type in ['in_invoice', 'in_refund']:
            email_template = self.env.ref('l10n_cr_ticofac.email_template_invoice_vendor', False)
        else:
            email_template = self.env.ref('account.email_template_edi_invoice', False)

        attachments = get_invoice_attachments(inv, inv.id)

        if len(attachments) == 2:
            email_template.attachment_ids = [(6, 0, attachments)]

            try:
                email_template.with_context(type='binary', default_type='binary').send_mail(inv.id,
                                                                                            raise_exception=False,
                                                                                            force_send=True)
            except Exception:
                _logger.error('FECR - consulta documento error al enviar correo: %s', inv.number_electronic)

            # limpia el template de los attachments
            email_template.attachment_ids = [(5, 0, 0)]

def send_message(inv, date_cr, xml, token, env):
    endpoint = fe_enums.UrlHaciendaRecepcion[env]

    vat = re.sub('[^0-9]', '', inv.partner_id.vat)
    xml_base64 = string_to_base64(xml)

    comprobante = {
        'clave': inv.number_electronic,
        'consecutivoReceptor': inv.consecutive_number_receiver,
        "fecha": date_cr,
        'emisor': {
            'tipoIdentificacion': str(inv.partner_id.identification_id.code),
            'numeroIdentificacion': vat
        },
        'receptor': {
            'tipoIdentificacion': str(inv.company_id.identification_id.code),
            'numeroIdentificacion': inv.company_id.vat
        },
        'comprobanteXml': xml_base64
    }

    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer {}'.format(token)
    }
    try:
        response = requests.post(endpoint, data=json.dumps(comprobante), headers=headers)

    except requests.exceptions.RequestException as e:
        _logger.info('Exception %s', e)
        return {'status': 400, 'text': 'Excepción de envio XML'}
        # raise Exception(e)

    if (200 <= response.status_code <= 299):
        return {'status': response.status_code, 'text': response.text}

    _logger.error('E-INV CR - ERROR SEND MESSAGE - RESPONSE:%s', response.headers.get('X-Error-Cause', 'Unknown'))
    return {'status': response.status_code, 'text': response.headers.get('X-Error-Cause', 'Unknown')}

def load_xml_data(invoice, load_lines, account_id, product_id=False, analytic_account_id=False):
    try:
        invoice_xml = etree.fromstring(base64.b64decode(invoice.xml_supplier_approval))
        document_type = re.search('FacturaElectronica|NotaCreditoElectronica|NotaDebitoElectronica|TiqueteElectronico', invoice_xml.tag).group(0)
        document_version = re.search('4.3|4.4', invoice_xml.tag).group(0)

        if document_type == 'TiqueteElectronico':
            raise UserError(_("This is a TICKET only invoices are valid for taxes"))

    except Exception as e:
        raise UserError(_("This XML file is not XML-compliant. Error: %s") % e)

    namespaces = invoice_xml.nsmap
    inv_xmlns = namespaces.pop(None)
    namespaces['inv'] = inv_xmlns
    tipo_map = {
        '01': 'FE',  #
        '02': 'ND',  # Nota Débito Electrónica
        '03': 'NC',  # Nota Crédito Electrónica
        '04': 'TE',  # Tiquete Electrónico
        '05': 'FEX',  # Factura de Exportación
        '06': 'FCA',  # Factura de Compra
        '07': 'NDE',  # Nota de Envío
    }
    issuer_activity_id,receiver_activity_id,activity,issuer_neighborhood,other_charges_node = False, False, False, False, False


    # Se ajust diferencias entre versiones de Factura electrónica
    if document_version == '4.3':
        issuer_activity_node = invoice_xml.xpath("inv:CodigoActividad", namespaces=namespaces)
        payment_method_node = invoice_xml.xpath("inv:MedioPago", namespaces=namespaces)
    elif document_version == '4.4':
        issuer_activity_node = invoice_xml.xpath("inv:CodigoActividadEmisor", namespaces=namespaces)
        receiver_activity_node = invoice_xml.xpath("inv:CodigoActividadReceptor", namespaces=namespaces)
        payment_method_node = invoice_xml.xpath("inv:ResumenFactura/inv:MedioPago/inv:TipoMedioPago", namespaces=namespaces)
        other_charges_node = invoice_xml.xpath("inv:OtrosCargos", namespaces=namespaces)      

    if issuer_activity_node:
        activity = invoice.env['economic.activity'].with_context(active_test=False).search(
            [
                ('code', '=', issuer_activity_node[0].text)
            ],
            limit=1
        )
        issuer_activity_id = activity.id
    elif receiver_activity_node:
        activity = invoice.env['economic.activity'].with_context(active_test=False).search(
            [
                ('code', '=', receiver_activity_id[0].text)
            ],
            limit=1
        )
        receiver_activity_id = activity.id
    # ---  Información General del Documento Electrónico --- #
    invoice.ref = invoice_xml.xpath("inv:NumeroConsecutivo", namespaces=namespaces)[0].text
    invoice.number_electronic = invoice_xml.xpath("inv:Clave", namespaces=namespaces)[0].text
    invoice.partner_economic_activity_id = issuer_activity_id
    invoice.economic_activity_id = receiver_activity_id or invoice.company_id.activity_id.id
    invoice.date_issuance = invoice_xml.xpath("inv:FechaEmision", namespaces=namespaces)[0].text
    invoice.invoice_date = invoice.date_issuance
    invoice.amount_total_electronic_invoice = float(invoice_xml.xpath("inv:ResumenFactura/inv:TotalComprobante", namespaces=namespaces)[0].text)
    if payment_method_node:
        invoice.payment_methods_id = invoice.env['payment.methods'].search([('id','=',payment_method_node[0].text)],limit=1).id
            
    tipo_codigo = invoice_xml.xpath("inv:NumeroConsecutivo", namespaces=namespaces)[0].text[8:10]  # posiciones 9-10    
    invoice.tipo_documento = tipo_map.get(tipo_codigo, False)
    currency_node = invoice_xml.xpath("inv:ResumenFactura/inv:CodigoTipoMoneda/inv:CodigoMoneda",
                                      namespaces=namespaces)
    if currency_node:
        invoice.currency_id = invoice.env['res.currency'].search([('name', '=', currency_node[0].text)], limit=1).id
    else:
        invoice.currency_id = invoice.env['res.currency'].search([('name', '=', 'CRC')], limit=1).id

    # ---  Información del Emisor --- #
    issuer_identification = invoice_xml.xpath("inv:Emisor/inv:Identificacion/inv:Numero", namespaces=namespaces)[0].text
    issuer_identification_type = invoice_xml.xpath("inv:Emisor/inv:Identificacion/inv:Tipo", namespaces=namespaces)[0].text
    issuer_name = invoice_xml.xpath("inv:Emisor/inv:Nombre", namespaces=namespaces)[0].text
    issuer_phone_node = invoice_xml.xpath("inv:Emisor/inv:Telefono/inv:NumTelefono", namespaces=namespaces)
    issuer_phone = issuer_phone_node[0].text if issuer_phone_node else ''
    issuer_country = invoice.env['res.country'].search([('name', '=', 'Costa Rica')], limit=1).id
    issuer_state_id = invoice_xml.xpath("inv:Emisor/inv:Ubicacion/inv:Provincia", namespaces=namespaces)[0].text
    issuer_state = invoice.env['res.country.state'].search(
        [('code','=',issuer_state_id)]
    )
    issuer_county_id = invoice_xml.xpath("inv:Emisor/inv:Ubicacion/inv:Canton", namespaces=namespaces)[0].text
    issuer_county = invoice.env['res.country.county'].search(
        [
            ('code','=',issuer_county_id),
            ('state_id','=',issuer_state_id)
            
        ]
    )
    issuer_district_id = invoice_xml.xpath("inv:Emisor/inv:Ubicacion/inv:Distrito", namespaces=namespaces)[0].text
    issuer_district = invoice.env['res.country.district'].search(
        [
            ('code','=',issuer_district_id),
            ('county_id.code','=',issuer_county_id),
            ('county_id.state_id','=',issuer_state_id)
        ]
    )
    issuer_neighborhood_id = invoice_xml.xpath("inv:Emisor/inv:Ubicacion/inv:Barrio", namespaces=namespaces)
    if issuer_neighborhood_id:
        issuer_neighborhood = invoice.env['res.country.neighborhood'].search(
            [
                ('code','=',issuer_neighborhood_id[0].text),
                ('district_id.code','=',issuer_district_id),
                ('district_id.county_id.code','=',issuer_county_id),
                ('district_id.county_id.state_id','=',issuer_state_id)
            ]
        )
    issuer_street = invoice_xml.xpath("inv:Emisor/inv:Ubicacion/inv:OtrasSenas", namespaces=namespaces)[0].text
    issuer_email = invoice_xml.xpath("inv:Emisor/inv:CorreoElectronico", namespaces=namespaces)[0].text

    # ---  Información del Receptor --- #
    receiver_node = invoice_xml.xpath("inv:Receptor/inv:Identificacion/inv:Numero", namespaces=namespaces)
    if receiver_node:
        receiver_identification = receiver_node[0].text
    else:
        raise UserError(_('El receptor no está definido en el xml'))

    if receiver_identification != invoice.company_id.vat:
        raise UserError(_('El receptor no corresponde con la compañía actual con identificación ' +
                          receiver_identification + '. Por favor active la compañía correcta.'))

    partner = invoice.env['res.partner'].search(
        [
            ('vat', '=', issuer_identification), '|',
            ('company_id', '=', invoice.company_id.id),
            ('company_id', '=', False)
        ],
        limit=1
    )

    if partner:
        if len(partner.activity_id.ids) == 0:
            partner.action_get_economic_activities()
        invoice.partner_id = partner
    else:
        new_partner_data = {
            'name': issuer_name,
            'vat': issuer_identification,
            'identification_id': issuer_identification_type,
            'company_type': 'company' if issuer_identification_type == '02' else 'person',
            'activity_id': issuer_activity_id,
            'type': 'contact',
            'country_id': issuer_country,
            'state_id': issuer_state.id,
            'county_id': issuer_county.id,
            'district_id': issuer_district.id,
            'phone': issuer_phone,
            'email': issuer_email,
            'street': issuer_street,
            'supplier_rank': 1
        }
        if issuer_neighborhood:
            new_partner_data['neighborhood_id'] = issuer_neighborhood.id

        new_partner = invoice.env['res.partner'].create(new_partner_data)
        new_partner.action_get_economic_activities()
        if new_partner:
            invoice.partner_id = new_partner
        else:
            raise UserError(_('The provider in the invoice does not exists. ' +
                              'I tried to created without success. Please review it.'))

    invoice.invoice_payment_term_id = partner.property_supplier_payment_term_id
    
    _logger.debug('FECR - load_lines: %s - account: %s', (load_lines, account_id))

    product = False
    if product_id:
        copy_product = product_id.copy()
        copy_product.name = product_id.name
        product = copy_product.id

    analytic_account = False
    if analytic_account_id:
        analytic_account = analytic_account_id.id

    # if load_lines and not invoice.invoice_line_ids:
    if load_lines:
        lines = invoice_xml.xpath("inv:DetalleServicio/inv:LineaDetalle", namespaces=namespaces)
        new_lines = []

        for line in lines:
            product_uom = invoice.env['uom.uom'].search(
                [('code', '=', line.xpath("inv:UnidadMedida", namespaces=namespaces)[0].text)],
                limit=1).id
            total_amount = float(line.xpath("inv:MontoTotal", namespaces=namespaces)[0].text)

            discount_percentage = 0.0
            discount_note = None

            if total_amount > 0:
                # Buscar nodo Descuento (si viene agrupado)
                discount_node = line.xpath("inv:Descuento", namespaces=namespaces)

                if discount_node:
                    descuento = discount_node[0]
                    monto_desc = descuento.xpath("inv:MontoDescuento", namespaces=namespaces)
                    naturaleza = descuento.xpath("inv:NaturalezaDescuento", namespaces=namespaces)
                else:
                    monto_desc = line.xpath("inv:MontoDescuento", namespaces=namespaces)
                    naturaleza = line.xpath("inv:NaturalezaDescuento", namespaces=namespaces)

                if total_amount > 0:
                    discount_node = line.xpath("inv:Descuento", namespaces=namespaces)
                    if discount_node:
                        discount_amount_node = discount_node[0].xpath("inv:MontoDescuento", namespaces=namespaces)[0]
                        discount_amount = float(discount_amount_node.text or '0.0')
                        discount_percentage = discount_amount / total_amount * 100
                        discount_note = discount_node[0].xpath("inv:NaturalezaDescuento", namespaces=namespaces)[0].text
                    else:
                        discount_amount_node = line.xpath("inv:MontoDescuento", namespaces=namespaces)
                        if discount_amount_node:
                            discount_amount = float(discount_amount_node[0].text or '0.0')
                            discount_percentage = discount_amount / total_amount * 100
                            discount_note = line.xpath("inv:NaturalezaDescuento", namespaces=namespaces)[0].text

            total_tax = 0.0
            taxes = []
            tax_nodes = line.xpath("inv:Impuesto", namespaces=namespaces)
            dict_tax = {}
            for tax_node in tax_nodes:
                tax_code = re.sub(r"[^0-9]+", "", tax_node.xpath("inv:Codigo", namespaces=namespaces)[0].text)
                tax_amount = float(tax_node.xpath("inv:Tarifa", namespaces=namespaces)[0].text)
                _logger.debug('FECR - tax_code: %s', tax_code)
                _logger.debug('FECR - tax_amount: %s', tax_amount)

                if product_id and product_id.non_tax_deductible:
                    tax = invoice.env['account.tax'].search(
                        [('tax_code', '=', tax_code),
                         ('amount', '=', tax_amount),
                         ('type_tax_use', '=', 'purchase'),
                         ('non_tax_deductible', '=', True),
                         ('active', '=', True)],
                        limit=1)
                else:
                    tax = invoice.env['account.tax'].search(
                        [('tax_code', '=', tax_code),
                         ('amount', '=', tax_amount),
                         ('type_tax_use', '=', 'purchase'),
                         ('non_tax_deductible', '=', False),
                         ('active', '=', True)],
                        limit=1)

                if tax:
                    # uno de los errores de por qué hay diferencia en los decimáles es
                    # porque el sistema no considera el campo total_tax para calcular el total de cada impuesto.
                    # El otro error de por qué hay diferencia al imprimir los reportes,
                    # es debido a que el monto de impuesto otros no lo toma del xml, sino se calcula desde el sql.
                    tax_node_amount = float(tax_node.xpath("inv:Monto", namespaces=namespaces)[0].text)
                    total_tax += tax_node_amount

                    if tax.id not in dict_tax:
                        dict_tax[tax.id] = {'amount': 0.0}

                    dict_tax[tax.id].update(amount=dict_tax[tax.id]['amount'] + tax_node_amount)

                    exonerations = tax_node.xpath("inv:Exoneracion", namespaces=namespaces)
                    if exonerations:
                        for exoneration_node in exonerations:
                            exoneration_percentage = float(
                                exoneration_node.xpath("inv:PorcentajeExoneracion", namespaces=namespaces)[0].text)
                            tax = invoice.env['account.tax'].search(
                                [('percentage_exoneration', '=', exoneration_percentage),
                                 ('type_tax_use', '=', 'purchase'),
                                 ('non_tax_deductible', '=', False),
                                 ('has_exoneration', '=', True),
                                 ('active', '=', True)],
                                limit=1)

                            if tax:
                                taxes.append((4, tax.id))
                    else:
                        taxes.append((4, tax.id))
                else:
                    if product_id and product_id.non_tax_deductible:
                        invoice.message_post(
                            body='Tax code %s and percentage %s as non-tax deductible is not registered in the system' % (
                            tax_code, tax_amount))
                        _logger.info(
                            'Tax code %s and percentage %s as non-tax deductible is not registered in the system' % (
                            tax_code, tax_amount))
                    else:
                        _logger.info('Tax code %s and percentage %s is not registered in the system' % (tax_code, tax_amount))
                        invoice.message_post(
                            body='Tax code %s and percentage %s is not registered in the system' % (
                                tax_code, tax_amount))

            _logger.debug('FECR - line taxes: %s' % (taxes))
            invoice_line = invoice.env['account.move.line'].create({
                'name': line.xpath("inv:Detalle", namespaces=namespaces)[0].text,
                'move_id': invoice.id,
                'price_unit': line.xpath("inv:PrecioUnitario", namespaces=namespaces)[0].text,
                'quantity': line.xpath("inv:Cantidad", namespaces=namespaces)[0].text,
                #'uom_id': product_uom,
                'sequence': line.xpath("inv:NumeroLinea", namespaces=namespaces)[0].text,
                'discount': discount_percentage,
                # 'price_subtotal' =
                'discount_note': discount_note,
                # 'total_amount': total_amount,
                'product_id': product,
                #'account_id': account_id.id or False,
                #'account_analytic_id': analytic_account,
                # 'amount_untaxed': float(line.xpath("inv:SubTotal", namespaces=namespaces)[0].text),
                'total_tax': total_tax,
                'display_type': 'product',
                'economic_activity_id': invoice.economic_activity_id.id,
                "tax_ids": taxes
            })

            #invoice_line.price_unit = line.xpath("inv:PrecioUnitario", namespaces=namespaces)[0].text
            #invoice_line

            # This must be assigned after line is created
            # invoice_line.tax_ids = taxes
            # invoice_line.economic_activity_id = activity
            new_lines += invoice_line
            if not invoice.invoice_line_ids:
                invoice.unlink()
                raise UserError('Documento no cuenta con lineas de detalles.')
        
        # Se agregan Otro Cargos a la factura        
        if other_charges_node:
            for other_charges in other_charges_node:
                product_oc = invoice.env['product.product'].search([('name', '=', 'Otros Cargos')], limit=1)

                # Crear linea de factura con Otros Cargos
                invoice_line_oc = invoice.env['account.move.line'].create({
                'name': other_charges.find("inv:Detalle", namespaces=namespaces).text,
                'move_id': invoice.id,
                'price_unit': other_charges.find("inv:MontoCargo", namespaces=namespaces).text,
                'quantity': 1,
                'product_id': product_oc.id,
                'display_type': 'product',
                "tax_ids": [(6, 0, [])]
            })

def p12_expiration_date(p12file, password):
    if not p12file or not password:
        return False

    _private_key, certificate, _additional_certificates = (
        pkcs12.load_key_and_certificates(
            base64.b64decode(p12file),
            password.encode("utf-8"),
        )
    )
    if not certificate:
        raise ValueError(_("El archivo no contiene un certificado válido."))

    expiration = getattr(certificate, "not_valid_after_utc", None)
    if expiration is None:
        expiration = certificate.not_valid_after
    if expiration.tzinfo:
        expiration = expiration.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return expiration

def normalize_neighborhood(name: str) -> str:
    """
    Ensures the <Barrio> value meets Hacienda's minLength=5 rule.

    - Empty input  → returns "" (caller should skip the tag).
    - Length ≤ 4   → prepends 'Barrio ' to reach ≥ 5 characters.
    - Always XML-escapes the result.

    Parameters
    ----------
    name : str
        The raw neighborhood name from the database.

    Returns
    -------
    str
        A normalized, XML-safe string (or empty if name is falsy).
    """
    if not name:
        return ""
    name = name.strip()
    if len(name) < 5:  # 1-4 chars trigger prefix
        name = f"Barrio {name}"
    return escape(name)
    return escape(name)
