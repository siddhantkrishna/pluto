/* Google Picker needs a short-lived OAuth access token, never a refresh token. */
window.plutoPick = function (config) {
  return new Promise(function (resolve, reject) {
    function open() {
      gapi.load('picker', function () {
        const picker = new google.picker.PickerBuilder()
          .setDeveloperKey(config.api_key).setAppId(config.app_id)
          .setOAuthToken(config.access_token).setOrigin(window.location.origin)
          .addView(google.picker.ViewId.DOCS)
          .enableFeature(google.picker.Feature.MULTISELECT_ENABLED)
          .setCallback(function (data) {
            if (data.action === google.picker.Action.PICKED) resolve(data.docs.map(function (doc) { return doc.id; }));
            if (data.action === google.picker.Action.CANCEL) resolve([]);
          }).build();
        picker.setVisible(true);
      });
    }
    if (window.gapi) open();
    else {
      const script = document.createElement('script');
      script.src = 'https://apis.google.com/js/api.js'; script.onload = open;
      script.onerror = function () { reject(new Error('Google Picker could not load')); };
      document.head.appendChild(script);
    }
  });
};
