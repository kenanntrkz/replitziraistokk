/**
 * Bag Analiz Script
 * Showdown markdown converter kullanarak bag analiz sonuclarini gosterir
 * /api/bag-analiz endpoint'inden veri ceker
 */

document.addEventListener('DOMContentLoaded', function() {

    // Bag analiz butonu
    var bagAnalizBtn = document.getElementById('bagAnalizBtn');
    var bagAnalizSonuc = document.getElementById('bagAnalizSonuc');
    var bagAnalizKaynak = document.getElementById('bagAnalizKaynak');

    if (bagAnalizBtn) {
        bagAnalizBtn.addEventListener('click', function() {
            var bagId = this.getAttribute('data-bag-id');

            if (!bagId) {
                alert('Bag ID bulunamadi.');
                return;
            }

            // Yukleniyor durumu
            bagAnalizBtn.disabled = true;
            bagAnalizBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analiz yapiliyor...';

            if (bagAnalizSonuc) {
                bagAnalizSonuc.style.display = 'block';
                bagAnalizSonuc.innerHTML = '<div class="text-center p-4"><i class="fas fa-spinner fa-spin fa-2x"></i><br><br>Yapay zeka bag analizini hazirlaniyor, bu islem birkaç saniye surebilir...</div>';
            }

            fetch('/api/bag-analiz', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ bag_id: parseInt(bagId) })
            })
            .then(function(response) {
                return response.json();
            })
            .then(function(data) {
                if (data.error) {
                    if (bagAnalizSonuc) {
                        bagAnalizSonuc.innerHTML = '<div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i> ' + data.error + '</div>';
                    }
                    return;
                }

                // Kaynak bilgisi
                if (bagAnalizKaynak && data.kaynak) {
                    bagAnalizKaynak.style.display = 'inline-block';
                    bagAnalizKaynak.textContent = data.kaynak;
                }

                // Markdown'i HTML'e cevir
                var analizHtml = '';
                if (data.analiz) {
                    if (typeof showdown !== 'undefined') {
                        var converter = new showdown.Converter({
                            tables: true,
                            tasklists: true,
                            strikethrough: true,
                            emoji: true,
                            simpleLineBreaks: true
                        });
                        analizHtml = converter.makeHtml(data.analiz);
                    } else {
                        // Showdown yuklu degilse basit donusum
                        analizHtml = data.analiz
                            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                            .replace(/\*(.*?)\*/g, '<em>$1</em>')
                            .replace(/### (.*)/g, '<h5 class="mt-3">$1</h5>')
                            .replace(/## (.*)/g, '<h4 class="mt-3">$1</h4>')
                            .replace(/# (.*)/g, '<h3 class="mt-3">$1</h3>')
                            .replace(/^- (.*)/gm, '<li>$1</li>')
                            .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
                            .replace(/\n\n/g, '</p><p>')
                            .replace(/\n/g, '<br>');
                        analizHtml = '<p>' + analizHtml + '</p>';
                    }
                } else {
                    analizHtml = '<div class="alert alert-info">Analiz sonucu bos dondu.</div>';
                }

                if (bagAnalizSonuc) {
                    bagAnalizSonuc.innerHTML = '<div class="card"><div class="card-body bag-analiz-icerik">' + analizHtml + '</div></div>';
                }
            })
            .catch(function(err) {
                console.error('Bag analiz hatasi:', err);
                if (bagAnalizSonuc) {
                    bagAnalizSonuc.innerHTML = '<div class="alert alert-danger"><i class="fas fa-times-circle"></i> Analiz sirasinda bir hata olustu: ' + err.message + '</div>';
                }
            })
            .finally(function() {
                bagAnalizBtn.disabled = false;
                bagAnalizBtn.innerHTML = '<i class="fas fa-robot"></i> AI ile Bag Analizi';
            });
        });
    }

});
