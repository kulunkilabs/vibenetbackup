// VIBENetBackup - Frontend JS

// HTMX configuration
document.addEventListener('DOMContentLoaded', function() {
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
