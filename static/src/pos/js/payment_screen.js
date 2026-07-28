/** @odoo-module **/

import {patch} from "@web/core/utils/patch";
import {PaymentScreen} from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { CreditNotePopup } from "./credit_note_popup";


patch(PaymentScreen.prototype, {
    shouldDownloadInvoice() {
        return null;
    },
    setup() {
        super.setup(...arguments);
        this.orm = this.env.services.orm;
        this.dialog = this.env.services.dialog;
        this.tipo_documento = null;
    },

    /**
     * Show an error dialog with the validation error message.
     * This ensures the user clearly sees what fields are missing.
     * 
     * @param {string} errorMessage - The error message to display
     * @param {Array} missingFields - Optional list of missing fields
     */
    _showValidationErrorDialog(errorMessage, missingFields = []) {
        let body = errorMessage;
        
        // If we have specific missing fields, format them nicely
        if (missingFields && missingFields.length > 0) {
            const fieldList = missingFields.map(field => `  • ${field}`).join('\n');
            body = _t(
                "No se puede completar la operación.\n\n" +
                "Campos faltantes requeridos por Hacienda:\n" +
                "%s\n\n" +
                "Por favor complete la información del cliente antes de continuar."
            ).replace('%s', fieldList);
        }

        this.dialog.add(ConfirmationDialog, {
            title: _t("Error de Validación - Factura Electrónica"),
            body: body,
            confirmLabel: _t("Entendido"),
        });

    },

    /**
     * Validate order data for electronic invoicing BEFORE submitting the order.
     * This validates both partner data and CABYS codes.
     * Provides early feedback to the user about missing data.
     * 
     * @returns {Promise<boolean>} True if validation passes, false otherwise
     */
    async _validateOrderForFE() {
        const order = this.pos.get_order();
        
        // If not electronic invoicing company, skip validation
        if (!this.pos.company.invoice_is_electronic) {
            return true;
        }

        // If TE, skip strict partner validation (but still validate CABYS)
        // TE still needs CABYS codes for XML generation
        
        // Get partner ID
        const partnerId = order.partner_id?.id || this.pos.config.default_partner_id?.id;
        
        // Get product IDs from order lines
        // In POS, orderlines have a 'product' property which is the product object
        // The product ID can be accessed via product.id
        const orderlines = order.get_orderlines();
        const lineProductIds = orderlines
            .filter(line => {
                // In POS, product can be accessed via line.product or line.get_product()
                const product = line.product || (line.get_product && line.get_product());
                return product && product.id;
            })
            .map(line => {
                const product = line.product || (line.get_product && line.get_product());
                return product.id;
            });

        // Check if this is a refund and determine original document type + refunded line IDs
        let originalTipoDocumento = false;
        let refundedOrderlineIds = [];
        
        if (this.tipo_documento === 'NC') {
            const orderlines = order.get_orderlines();
            for (const line of orderlines) {
                // Check for refunded order reference safely
                if (line.refunded_orderline_id) {
                    // Collect the refunded orderline ID for backend lookup
                    if (line.refunded_orderline_id.id) {
                        refundedOrderlineIds.push(line.refunded_orderline_id.id);
                    }
                    // Try to get tipo_documento from frontend (may not be loaded)
                    const originalOrder = line.refunded_orderline_id.order_id;
                    if (originalOrder && originalOrder.get_tipo_documento && originalOrder.get_tipo_documento() && !originalTipoDocumento) {
                        originalTipoDocumento = originalOrder.get_tipo_documento();
                    }
                }
            }
            console.log("🔍 NC Validation: Original Doc Type =", originalTipoDocumento, "Refunded Line IDs =", refundedOrderlineIds);
        }

        try {
            // Call backend validation - validates both partner and CABYS
            // Pass refundedOrderlineIds so backend can look up original tipo_documento if needed
            const validationResult = await this.orm.call(
                "pos.order",
                "validate_order_for_pos_fe",
                [partnerId, this.tipo_documento, lineProductIds, this.pos.company.id, originalTipoDocumento, refundedOrderlineIds]
            );

            if (!validationResult.valid) {
                console.warn("❌ FE Validation failed:", validationResult);
                this._showValidationErrorDialog(validationResult.error_message);
                return false;
            }

            // Validate discount codes for lines with discounts
            const discountCodeValidation = await this._validateDiscountCodes();
            if (!discountCodeValidation) {
                return false;
            }

            console.log("✅ FE Order validation passed (client + CABYS + discount codes)");
            return true;

        } catch (error) {
            console.error("❌ Error during FE validation:", error);
            // Show error but allow continuing (backend will validate again)
            this._showValidationErrorDialog(
                _t("Error al validar los datos del pedido. Por favor intente nuevamente.")
            );
            return false;
        }
    },

    /**
     * Validate that all order lines with discounts have a discount code selected.
     * Skip validation for Credit Notes (NC) as they use the original document's discount codes.
     * 
     * @returns {Promise<boolean>} True if validation passes, false otherwise
     */
    async _validateDiscountCodes() {
        const order = this.pos.get_order();
        if (!order) return true;

        // Skip discount code validation for Credit Notes (NC) / Refunds
        // NC inherits discount codes from the original document
        if (this.tipo_documento === 'NC') {
            console.log("✅ Skipping discount code validation for NC (Credit Note)");
            return true;
        }

        const orderlines = order.get_orderlines();
        const linesData = orderlines
            .filter(line => {
                const product = line.product || (line.get_product && line.get_product());
                return product && line.discount > 0;
            })
            .map(line => {
                const product = line.product || (line.get_product && line.get_product());
                // Use discountCodeId (camelCase) or getDiscountCodeId() method to avoid Odoo proxy issues
                const codeId = line.discountCodeId || (line.getDiscountCodeId ? line.getDiscountCodeId() : null);
                return {
                    product_name: product.display_name || product.name || "Unknown",
                    discount: line.discount,
                    discount_code_id: codeId || false,
                };
            });

        // If no lines with discounts, validation passes
        if (linesData.length === 0) {
            return true;
        }

        try {
            const validationResult = await this.orm.call(
                "pos.order",
                "validate_discount_codes_for_pos",
                [linesData, this.pos.company.id]
            );

            if (!validationResult.valid) {
                console.warn("❌ Discount code validation failed:", validationResult);
                this._showValidationErrorDialog(validationResult.error_message);
                return false;
            }

            return true;
        } catch (error) {
            console.error("❌ Error during discount code validation:", error);
            return true; // Allow continuing, backend will validate again
        }
    },

    async validateOrder(isForceValidate) {
        const order = this.pos.get_order();

        if (this.pos.company.invoice_is_electronic && order) {
            order.to_invoice = true;

            const partner_domain = order.partner_id
                ? [["id", "=", order.partner_id.id]]
                : [["id", "=", this.pos.config.default_partner_id.id]];
            const checkPartner = await this.orm
                .call("res.partner", "search_read", [], {
                    domain: partner_domain,
                    fields: ["id", "name", "email", "inscribed", "vat"],
                })
                .catch((e) => {
                    console.error("❌ Error consultando partner:", e);
                    return [];
                });

            if (checkPartner.length) {
                // Buscar el partner en la cache del POS
                const partner =
                    this.pos.models["res.partner"]?.get(checkPartner[0].id) || null;

                if (!order.get_partner() && partner) {
                    order.set_partner(partner);
                    console.log("✅ Cliente asignado al pedido:", partner.name);
                }
                
                // Determine Document Type
                // If amount is negative, it's a Credit Note (NC)
                // Otherwise checks if partner is inscribed (FE) or not (TE)
                const isRefund = order.get_total_with_tax() < 0;
                
                if (isRefund) {
                     this.tipo_documento = "NC";
                } else {
                     this.tipo_documento = checkPartner[0].inscribed ? "FE" : "TE";
                }
                
                order.set_tipo_documento(this.tipo_documento);
                
                // If it is a Credit Note (NC), ask for details
                if (this.tipo_documento === "NC") {
                    
                    // Try to get the original invoice number from refunded order lines
                    let originalInvoiceNumber = "";
                    const orderlines = order.get_orderlines();
                    for (const line of orderlines) {
                        if (line.refunded_orderline_id) {
                            const originalOrder = line.refunded_orderline_id.order_id;
                            if (originalOrder && originalOrder.get_number_electronic && originalOrder.get_number_electronic()) {
                                originalInvoiceNumber = originalOrder.get_number_electronic();
                                break;
                            }
                        }
                    }
                    
                    let refundDetails = null;
                    
                    await new Promise((resolve) => {
                        this.dialog.add(CreditNotePopup, {
                            originalInvoiceNumber: originalInvoiceNumber,
                            getPayload: (payload) => {
                                refundDetails = payload;
                                resolve();
                            },
                            close: () => {
                                resolve();
                            }
                        });
                    });
                    
                    if (refundDetails) {
                        order.set_reason_refund(refundDetails.reason);
                        order.set_refund_reference_code_id(refundDetails.referenceCodeId);
                        console.log("✅ Credit Note Details Set:", refundDetails);
                    } else {
                         // If cancelled (no payload), stop validation
                         return;
                    }
                }
            }

            // -------------------------------------------------------------------------
            // EARLY ORDER VALIDATION FOR FE
            // -------------------------------------------------------------------------
            // Validate client/partner data and CABYS codes BEFORE generating electronic number
            // This prevents silent failures and provides clear feedback to the user
            const isOrderValid = await this._validateOrderForFE();
            if (!isOrderValid) {
                console.warn("❌ FE validation failed (partner or CABYS), stopping order processing");
                return; // Stop processing, validation dialog already shown
            }

            // Obtener el diario
            const [journal] = await this.orm.call("pos.config", "search_read", [], {
                domain: [["id", "=", this.pos.config.id]],
                fields: ["invoice_journal_id"],
                limit: 1,
            });

            const electronic_data = await this.generate_number_electronic(journal.invoice_journal_id[0]);
            
            if (!electronic_data) {
                this._showValidationErrorDialog(
                    _t("Error al generar el número electrónico. Por favor intente nuevamente.")
                );
                return;
            }
            
            order.set_number_electronic(electronic_data.clave);
            order.set_sequence(electronic_data.consecutivo);
        }

        // Call parent validateOrder - any backend errors will be caught by Odoo's error handling
        try {
            await super.validateOrder(...arguments);
        } catch (error) {
            // Handle backend validation errors (UserError from _validate_pos_order_partner_for_fe)
            console.error("❌ Error during order validation:", error);
            
            // Check if this is a UserError from our validation
            if (error.data && error.data.message) {
                this._showValidationErrorDialog(error.data.message);
            } else if (error.message) {
                this._showValidationErrorDialog(error.message);
            }
            // The error will stop the flow, loader should be handled by parent
        }
    },
    
    async generate_number_electronic(journalid) {
        try {
            const journal_data = await this.orm.call("account.journal", "search_read", [], {
                domain: [["id", "=", journalid]],
                fields: ["sucursal", "terminal", "FE_sequence_id", "TE_sequence_id", "NC_sequence_id"]
            });

            let seq_id;
            if (this.tipo_documento === "FE") {
                seq_id = journal_data[0].FE_sequence_id;
            } else if (this.tipo_documento === "TE") {
                seq_id = journal_data[0].TE_sequence_id;
            } else if (this.tipo_documento === "NC") {
                seq_id = journal_data[0].NC_sequence_id;
            }

            if (!seq_id) {
                console.error("❌ No sequence found for document type:", this.tipo_documento);
                return null;
            }
            
            const seq_data = await this.orm.call("ir.sequence", "search_read", [], {
                domain: [["id", "=", seq_id[0]]],
                fields: ["number_next_actual", "padding"]
            });

            const idict = {
                year: luxon.DateTime.local().toFormat("yyyy"),
                month: luxon.DateTime.local().toFormat("MM"),
                day: luxon.DateTime.local().toFormat("dd"),
                y: luxon.DateTime.local().toFormat("yy"),
            };

            function pad(n, width, z = "0") {
                n = n + "";
                return n.length < width ? new Array(width - n.length + 1).join(z) + n : n;
            }

            const vat = this.pos.company.vat;
            const num = seq_data[0].number_next_actual;
            
            let tipo_doc = "01";
            if (this.tipo_documento === "TE") {
                tipo_doc = "04";
            } else if (this.tipo_documento === "NC") {
                tipo_doc = "03";
            }

            // Consecutivo de 20 dígitos
            const consecutivo = pad(journal_data[0].sucursal, 3)
                + pad(journal_data[0].terminal, 5)
                + tipo_doc
                + pad(num, 10);

            // Clave de 50 dígitos
            const prefix = "506" + idict.day + idict.month + idict.y + pad(vat, 12);
            const situacion = "1";
            const codigo_seguridad = this.generarCodigoSeguridad();
            const clave = prefix + consecutivo + situacion + codigo_seguridad;

            if (clave.length !== 50) {
                throw new Error("La clave generada no tiene 50 dígitos: " + clave);
            }

            return {
                clave: clave,
                consecutivo: consecutivo,
            };

        } catch (error) {
            console.error("Error generating electronic number:", error);
            return null;
        }
    },
    generarCodigoSeguridad() {
        return Math.floor(10000000 + Math.random() * 90000000).toString();
    },
});
