const API_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8000'
    : '/api';

// Elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const browseBtn = document.getElementById('browse-btn');
const fileNameDisplay = document.getElementById('file-name');
const analyzeBtn = document.getElementById('analyze-btn');
const uploadSection = document.getElementById('upload-section');
const loadingSection = document.getElementById('loading-section');
const resultsSection = document.getElementById('results-section');
const resultsContainer = document.getElementById('results-container');
const resetBtn = document.getElementById('reset-btn');
const saveBtn = document.getElementById('save-btn');
const downloadPdfBtn = document.getElementById('download-pdf-btn');
const patientNameInput = document.getElementById('patient-name');

let selectedFile = null;
let currentItems = [];

// Drag & Drop
dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    handleFiles(e.dataTransfer.files);
});

// File Selection
browseBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', (e) => handleFiles(e.target.files));

function handleFiles(files) {
    if (files.length > 0) {
        selectedFile = files[0];
        fileNameDisplay.textContent = `Selected: ${selectedFile.name}`;
        analyzeBtn.disabled = false;
    }
}

// Analyze
analyzeBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    showLoading();

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
        const response = await fetch(`${API_URL}/analyze`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error("API Error Response:", errorText);
            try {
                const errorData = JSON.parse(errorText);
                throw new Error(errorData.detail || 'Analysis failed');
            } catch (e) {
                throw new Error(`Server Error (${response.status}): ${errorText.substring(0, 100)}...`);
            }
        }

        const data = await response.json();
        currentItems = data;
        displayResults(data);
    } catch (error) {
        console.error("Full Error:", error);
        showNotification('Error: ' + error.message, 'error');
        showUpload();
    }
});

// Display Results
function displayResults(items) {
    uploadSection.hidden = true;
    loadingSection.hidden = true;
    resultsSection.hidden = false;
    resultsContainer.innerHTML = '';

    if (items.length === 0) {
        resultsContainer.innerHTML = '<p>No items found or analysis failed.</p>';
        return;
    }

    items.forEach(item => {
        const card = document.createElement('div');
        card.className = `treatment-item`; // urgency class handled by badge or border if needed

        card.innerHTML = `
            <div class="item-header">
                <div class="item-title">
                    ${item.friendly_name}
                    <div class="item-code">>> ${item.technical_name} [${item.code}]</div>
                </div>
                <div class="urgency-badge urgency-${item.urgency}">${item.urgency}</div>
            </div>
            
            <div class="item-explanation">
                ${item.explanation}
            </div>
            ${item.urgency_hook ? `<div style="margin-bottom: 1rem; font-style: italic; color: var(--accent-color);">WARN: "${item.urgency_hook}"</div>` : ''}
            <div class="item-price">
                ${item.price ? item.price.toLocaleString() + ' MMK' : 'PRICE_NULL'}
            </div>
        `;
        resultsContainer.appendChild(card);
    });
}

// Reset
resetBtn.addEventListener('click', () => {
    selectedFile = null;
    currentItems = [];
    fileInput.value = '';
    // fileNameDisplay.textContent = ''; // Removed from HTML or handled differently
    analyzeBtn.disabled = true;
    if (document.getElementById('download-pdf-btn')) {
        document.getElementById('download-pdf-btn').disabled = true;
    }
    showUpload();
});

// --- 3. Finalize Analysis (Client-Side Only) ---
saveBtn.addEventListener('click', async () => {
    if (!currentItems || currentItems.length === 0) {
        showNotification('No items to finalize!', 'error');
        return;
    }

    const patientName = patientNameInput.value.trim() || 'Unknown Patient';

    // Visual Feedback
    saveBtn.innerHTML = 'FINALIZED';
    saveBtn.disabled = true;
    saveBtn.style.background = '#0033CC';
    saveBtn.style.color = '#fff';

    // Show Notification
    showNotification('Session Finalized! Ready for PDF & Chat.');

    // Enable Actions
    downloadPdfBtn.hidden = false;
    downloadPdfBtn.disabled = false;

    // Chat Removed per user request (Quota limits)
});

// --- 4. Download PDF (Stateless) ---
downloadPdfBtn.addEventListener('click', async () => {
    const patientName = patientNameInput.value.trim() || 'Unknown Patient';

    downloadPdfBtn.innerHTML = 'GENERATING_PDF...';
    downloadPdfBtn.disabled = true;

    try {
        const response = await fetch(`${API_URL}/generate-pdf`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                items: currentItems,
                patient_name: patientName
            })
        });

        if (!response.ok) throw new Error('PDF Generation Failed');

        // Handle Blob
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `DentalPlan_${patientName.replace(/ /g, '_')}.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

        showNotification('PDF Downloaded!');
    } catch (error) {
        console.error(error);
        showNotification('Error generating PDF', 'error');
    } finally {
        downloadPdfBtn.innerHTML = 'DOWNLOAD_PDF';
        downloadPdfBtn.disabled = false;
    }
});

// Access Helper
function showUpload() {
    uploadSection.hidden = false;
    loadingSection.hidden = true;
    resultsSection.hidden = true;
    document.getElementById('terminal-output').innerHTML = ''; // Clear terminal
}

function showLoading() {
    uploadSection.hidden = true;
    loadingSection.hidden = false;
    resultsSection.hidden = true;
    runTerminalLoader();
}

// Enhancements: Terminal Loader
function runTerminalLoader() {
    const terminal = document.getElementById('terminal-output');
    terminal.innerHTML = '';
    const steps = [
        "INITIALIZING_CONNECTION...",
        "VERIFYING_INTEGRITY...",
        "UPLOAD_COMPLETE [OK]",
        "OCR_SCAN_INITIATED...",
        "EXTRACTING_TEXT_LAYER...",
        "CONNECTING_TO_GEMINI_NODE...",
        "ANALYZING_DENTAL_CODES...",
        "GENERATING_CLINICAL_INSIGHTS...",
        "COMPILING_RESULTS..."
    ];

    let delay = 0;
    steps.forEach((step, index) => {
        delay += Math.random() * 500 + 200; // Random delay between 200-700ms
        setTimeout(() => {
            const line = document.createElement('div');
            line.className = 'terminal-line';
            line.textContent = step;
            terminal.appendChild(line);
        }, delay);
    });
}

// Enhancements: Custom Notification
function showNotification(message, type = 'info') {
    const notif = document.getElementById('notification-area');
    notif.innerHTML = `
        <div style="font-weight: bold; margin-bottom: 0.5rem;">SYSTEM_MESSAGE:</div>
        <div>${message}</div>
    `;
    notif.classList.add('visible');

    // Auto hide after 4 seconds
    setTimeout(() => {
        notif.classList.remove('visible');
    }, 4000);
}
