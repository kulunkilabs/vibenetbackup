// VIBENetBackup - Frontend JS

// Initialize Bootstrap tooltips globally
function initTooltips(root) {
    (root || document).querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function(el) {
        bootstrap.Tooltip.getOrCreateInstance(el);
    });
}

// HTMX configuration
document.addEventListener('DOMContentLoaded', function() {
    initTooltips();

    // Re-init tooltips after any HTMX swap (new content may contain tooltip elements)
    document.body.addEventListener('htmx:afterSwap', function(evt) {
        initTooltips(evt.detail.target);
    });

    // Configure HTMX defaults
    document.body.addEventListener('htmx:configRequest', function(evt) {
        // Add any custom headers if needed
    });

    // Handle HTMX errors gracefully
    document.body.addEventListener('htmx:responseError', function(evt) {
        console.error('HTMX request failed:', evt.detail);
    });

    // Auto-dismiss alerts after 5 seconds
    document.querySelectorAll('.alert-dismissible').forEach(function(alert) {
        setTimeout(function() {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });
});
