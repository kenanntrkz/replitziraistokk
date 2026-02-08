/**
 * AI Gubre Ozellikleri
 * - Claude ile gubre otomatik doldurma (auto-fill)
 * - Gubre formulasyon aciklamasi alma
 */

document.addEventListener('DOMContentLoaded', function() {

    // ----- GUBRE ACIKLAMA BUTONU -----
    const gubreAciklaBtn = document.getElementById('gubreAciklaBtn');
    const gubreAciklamaDiv = document.getElementById('gubreAciklama');
    const formulasyonInput = document.getElementById('formulasyon');

    if (gubreAciklaBtn && gubreAciklamaDiv && formulasyonInput) {
        gubreAciklaBtn.addEventListener('click', function() {
            const formulasyon = formulasyonInput.value.trim();

            if (!formulasyon) {
                alert('Lutfen once gubre formulasyonunu girin (Orn: 18-18-18)');
                formulasyonInput.focus();
                return;
            }

            // Yukleniyor durumu
            gubreAciklaBtn.disabled = true;
            gubreAciklaBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analiz ediliyor...';
            gubreAciklamaDiv.style.display = 'block';
            gubreAciklamaDiv.innerHTML = '<div class="text-muted"><i class="fas fa-hourglass-half"></i> AI aciklama hazirlaniyor, lutfen bekleyin...</div>';

            fetch('/api/gubre-acikla', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ formulasyon: formulasyon })
            })
            .then(function(response) {
                return response.json();
            })
            .then(function(data) {
                if (data.error) {
                    gubreAciklamaDiv.innerHTML = '<div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i> ' + data.error + '</div>';
                } else {
                    let kaynakBadge = '';
                    if (data.kaynak) {
                        kaynakBadge = '<span class="badge bg-info mb-2">' + data.kaynak + '</span> ';
                    }

                    // Markdown icerik varsa showdown ile cevir
                    let aciklamaHtml = data.aciklama || 'Aciklama alinamadi.';
                    if (typeof showdown !== 'undefined') {
                        var converter = new showdown.Converter();
                        aciklamaHtml = converter.makeHtml(aciklamaHtml);
                    } else {
                        // Basit markdown donusumu
                        aciklamaHtml = aciklamaHtml
                            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                            .replace(/\*(.*?)\*/g, '<em>$1</em>')
                            .replace(/### (.*)/g, '<h6>$1</h6>')
                            .replace(/## (.*)/g, '<h5>$1</h5>')
                            .replace(/# (.*)/g, '<h4>$1</h4>')
                            .replace(/- (.*)/g, '<li>$1</li>')
                            .replace(/\n/g, '<br>');
                    }

                    gubreAciklamaDiv.innerHTML = '<div class="card"><div class="card-body">' + kaynakBadge + aciklamaHtml + '</div></div>';

                    // Perplexity linki varsa ekle
                    if (data.perplexity_url) {
                        gubreAciklamaDiv.innerHTML += '<div class="mt-2"><a href="' + data.perplexity_url + '" target="_blank" class="btn btn-sm btn-outline-primary"><i class="fas fa-external-link-alt"></i> Perplexity ile detayli arastir</a></div>';
                    }
                }
            })
            .catch(function(err) {
                console.error('Gubre aciklama hatasi:', err);
                gubreAciklamaDiv.innerHTML = '<div class="alert alert-danger"><i class="fas fa-times-circle"></i> Bir hata olustu: ' + err.message + '</div>';
            })
            .finally(function() {
                gubreAciklaBtn.disabled = false;
                gubreAciklaBtn.innerHTML = '<i class="fas fa-robot"></i> AI ile Aciklama Al';
            });
        });
    }

    // ----- CLAUDE AUTO-FILL: GUBRE ADI ILE OTOMATIK DOLDURMA -----
    const gubreAdInput = document.getElementById('ad');
    // Sadece gubre sayfasinda calistir (formulasyon input'u varsa gubre sayfasidir)
    if (gubreAdInput && formulasyonInput) {
        const claudeAutoFill = debounce(function(gubreAdi) {
            if (gubreAdi.length < 3) return;

            // Otomatik doldurma istegi gonder
            fetch('/api/gubre-auto-fill', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ gubre_adi: gubreAdi })
            })
            .then(function(response) {
                return response.json();
            })
            .then(function(data) {
                if (data.error) {
                    console.log('Auto-fill hatasi:', data.error);
                    return;
                }

                // Formulasyon alani bossa doldur
                if (data.formulasyon && !formulasyonInput.value.trim()) {
                    formulasyonInput.value = data.formulasyon;
                }

                // Kullanim alani bossa doldur
                var kullanimAlaniInput = document.getElementById('kullanim_alani');
                if (kullanimAlaniInput && data.kullanim_alani && !kullanimAlaniInput.value.trim()) {
                    kullanimAlaniInput.value = data.kullanim_alani;
                }

                // Not alani bossa aciklama ile doldur
                var notInput = document.getElementById('not_bilgisi');
                if (notInput && data.aciklama && !notInput.value.trim()) {
                    var notMetni = data.aciklama;
                    if (data.kullanim_zamani) {
                        notMetni += '\nKullanim Zamani: ' + data.kullanim_zamani;
                    }
                    notInput.value = notMetni;
                }
            })
            .catch(function(err) {
                console.log('Claude auto-fill hatasi:', err);
            });
        }, 1000);

        gubreAdInput.addEventListener('blur', function() {
            var gubreAdi = this.value.trim();
            if (gubreAdi.length >= 3) {
                claudeAutoFill(gubreAdi);
            }
        });
    }

});
