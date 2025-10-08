/*/////////////////////////////////////////////
create QR code to download Crush Quest contacts
*//////////////////////////////////////////////

const qrcode = require('qrcode');
const fs = require('fs');

// const vcfURL = "http://localhost:3545/download_contacts.html"
const vcfURL = "https://daily-co.github.io/pipecat-crush-quest/download_contacts.html"
const filePath = 'crush_quest_contacts_qr.png';
const dataToEncode = vcfURL;

// Generate QR code as a data URL (for embedding in HTML)
qrcode.toDataURL(dataToEncode, (err, url) => {
    if (err) {
        console.error(err);
        return;
    }
    console.log('QR Code Data URL:', url);
    // Use this 'url' in an <img> tag's src attribute in a web application.
});

// Generate QR code and save it as a PNG file
qrcode.toFile(filePath, dataToEncode, {
    errorCorrectionLevel: 'H' // Error correction level (L, M, Q, H)
}, (err) => {
    if (err) {
        console.error(err);
        return;
    }
    console.log(`QR Code saved to ${filePath}`);
});