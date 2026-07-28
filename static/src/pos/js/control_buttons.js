/** @odoo-module **/
/**
 * Control Buttons Extension for Discount Code (Costa Rica FE)
 * Patches the ControlButtons component to add a discount code selection button.
 */

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { DiscountCodePopup } from "./discount_code_popup";
import { _t } from "@web/core/l10n/translation";

// Patch ControlButtons to add discount code button handler
patch(ControlButtons.prototype, {
    /**
     * Handle click on discount code button - opens popup to select discount code
     */
    async onClickDiscountCode() {
        const order = this.pos.get_order();
        if (!order) {
            return;
        }

        const selectedLine = order.get_selected_orderline();
        if (!selectedLine) {
            this.env.services.notification.add(_t("Por favor seleccione una línea de producto primero"), {
                type: "warning",
            });
            return;
        }

        // Open the discount code popup
        this.env.services.dialog.add(DiscountCodePopup, {
            orderline: selectedLine,
            getPayload: (selectedCode) => {
                if (selectedCode !== undefined) {
                    selectedLine.setDiscountCode(selectedCode);
                    console.log("✅ Discount code set:", selectedCode?.name || "cleared");
                }
            },
        });
    },
});

console.log("✅ POS Discount Code - ControlButtons extension loaded");
