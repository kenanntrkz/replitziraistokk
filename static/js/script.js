/**
 * Tarim Ilac ve Gubre Stok Takip Sistemi - Ana Script
 * Genel yardimci fonksiyonlar, ilac arama, form islemleri
 */

// Onbellek atlatarak fetch yapan yardimci fonksiyon
function fetchNoCache(url, options = {}) {
    const separator = url.includes('?') ? '&' : '?';
    const noCacheUrl = url + separator + '_=' + Date.now();

    const defaultHeaders = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    };

    options.headers = Object.assign({}, defaultHeaders, options.headers || {});
    options.cache = 'no-store';

    return fetch(noCacheUrl, options);
}

// Debounce fonksiyonu - arka arkaya gelen cagrilari geciktirir
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Sayfa yuklendiginde calisacak kodlar
document.addEventListener('DOMContentLoaded', function() {

    // ----- ILAC ARAMA / AUTOCOMPLETE -----
    const ilacAdInput = document.getElementById('ad');
    const ilacListesi = document.getElementById('ilacListesi');

    if (ilacAdInput && ilacListesi) {
        // Ilac adi degistiginde bilgileri otomatik doldur
        ilacAdInput.addEventListener('change', function() {
            const seciliDeger = ilacAdInput.value;
            if (!seciliDeger) return;

            // Datalist'ten secilen option'i bul
            const options = ilacListesi.querySelectorAll('option');
            for (let i = 0; i < options.length; i++) {
                if (options[i].value === seciliDeger) {
                    const etkenMadde = options[i].getAttribute('data-etken') || '';
                    const hastalik = options[i].getAttribute('data-hastalik') || '';
                    const dozaj = options[i].getAttribute('data-dozaj') || '';

                    const etkenInput = document.getElementById('etken_madde');
                    const hastalikInput = document.getElementById('hedef_hastalik');
                    const dozajInput = document.getElementById('dozaj');

                    if (etkenInput) etkenInput.value = etkenMadde;
                    if (hastalikInput) hastalikInput.value = hastalik;
                    if (dozajInput && dozaj) dozajInput.value = dozaj;

                    break;
                }
            }
        });

        // Canlı arama (API'den sonuçları çek)
        const canliArama = debounce(function(sorgu) {
            if (sorgu.length < 2) return;

            fetchNoCache('/api/zirai-ilaclar/search?query=' + encodeURIComponent(sorgu))
                .then(response => response.json())
                .then(data => {
                    if (data && data.length > 0) {
                        // Mevcut datalist'e sonuclari ekle
                        data.forEach(function(ilac) {
                            const ilacAdi = ilac.ilac_adi || ilac.ad || '';
                            if (!ilacAdi) return;

                            // Zaten listede var mi kontrol et
                            let mevcut = false;
                            const mevcutOptions = ilacListesi.querySelectorAll('option');
                            for (let i = 0; i < mevcutOptions.length; i++) {
                                if (mevcutOptions[i].value === ilacAdi) {
                                    mevcut = true;
                                    break;
                                }
                            }

                            if (!mevcut) {
                                const option = document.createElement('option');
                                option.value = ilacAdi;
                                option.setAttribute('data-etken', ilac.etken_madde || '');
                                option.setAttribute('data-hastalik', ilac.hastalik || ilac.hedef_hastalik || '');

                                // Dozaj degerini al
                                let dozajDeger = ilac.dozaj || '0';
                                if (typeof dozajDeger === 'string') {
                                    const match = dozajDeger.match(/(\d+(?:\.\d+)?)/);
                                    dozajDeger = match ? match[1] : '0';
                                }
                                option.setAttribute('data-dozaj', dozajDeger);

                                ilacListesi.appendChild(option);
                            }
                        });
                    }
                })
                .catch(function(err) {
                    console.log('Ilac arama hatasi:', err);
                });
        }, 300);

        ilacAdInput.addEventListener('input', function() {
            canliArama(this.value);
        });
    }

    // ----- ILAC FORMU ISLEME -----
    const ilacForm = document.getElementById('ilacForm');
    if (ilacForm) {
        // Form gonderildiginde dogrulama
        ilacForm.addEventListener('submit', function(e) {
            const ad = document.getElementById('ad');
            const miktar = document.getElementById('miktar');
            const dozaj = document.getElementById('dozaj');

            if (ad && !ad.value.trim()) {
                e.preventDefault();
                alert('Lutfen ilac adini girin.');
                ad.focus();
                return false;
            }

            if (miktar && (!miktar.value || parseFloat(miktar.value) < 0)) {
                e.preventDefault();
                alert('Lutfen gecerli bir stok miktari girin.');
                miktar.focus();
                return false;
            }

            if (dozaj && (!dozaj.value || parseFloat(dozaj.value) < 0)) {
                e.preventDefault();
                alert('Lutfen gecerli bir dozaj degeri girin.');
                dozaj.focus();
                return false;
            }
        });
    }

    // ----- RAPOR FILTRESI -----
    const raporTuruSelect = document.getElementById('rapor_turu');
    if (raporTuruSelect) {
        raporTuruSelect.addEventListener('change', function() {
            const baslangicInput = document.getElementById('baslangic_tarih');
            const bitisInput = document.getElementById('bitis_tarih');

            if (this.value === 'ozel') {
                if (baslangicInput) baslangicInput.disabled = false;
                if (bitisInput) bitisInput.disabled = false;
            }
        });
    }

    // ----- TABLO SIRALAMA -----
    const siralamaBasliklari = document.querySelectorAll('th[data-sort]');
    siralamaBasliklari.forEach(function(baslik) {
        baslik.style.cursor = 'pointer';
        baslik.addEventListener('click', function() {
            const tablo = this.closest('table');
            const tbody = tablo.querySelector('tbody');
            const satirlar = Array.from(tbody.querySelectorAll('tr'));
            const sutunIndex = Array.from(this.parentNode.children).indexOf(this);
            const siralama = this.dataset.sortDir === 'asc' ? 'desc' : 'asc';

            satirlar.sort(function(a, b) {
                const aText = a.children[sutunIndex].textContent.trim();
                const bText = b.children[sutunIndex].textContent.trim();

                // Sayisal siralama dene
                const aNum = parseFloat(aText.replace(/[^\d.-]/g, ''));
                const bNum = parseFloat(bText.replace(/[^\d.-]/g, ''));

                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return siralama === 'asc' ? aNum - bNum : bNum - aNum;
                }

                // Metin siralama
                return siralama === 'asc'
                    ? aText.localeCompare(bText, 'tr')
                    : bText.localeCompare(aText, 'tr');
            });

            satirlar.forEach(function(satir) {
                tbody.appendChild(satir);
            });

            this.dataset.sortDir = siralama;
        });
    });

    // ----- ALERT OTOMATIK KAPATMA -----
    const alertler = document.querySelectorAll('.alert-dismissible');
    alertler.forEach(function(alert) {
        setTimeout(function() {
            const closeBtn = alert.querySelector('.btn-close');
            if (closeBtn) {
                closeBtn.click();
            }
        }, 5000);
    });

    // ----- NAVBAR AKTIF LINK -----
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.navbar-nav .nav-link');
    navLinks.forEach(function(link) {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });

});

// ----- ILAC KULLANIM SAYFASI: SATIR EKLEME -----
function ilacSatiriEkle() {
    const alan = document.getElementById('ilac-secim-alani');
    if (!alan) return;

    const ilkSelect = alan.querySelector('select[name="ilac_ids[]"]');
    if (!ilkSelect) return;

    const yeniSatir = document.createElement('div');
    yeniSatir.className = 'ilac-satir mb-2';

    const row = document.createElement('div');
    row.className = 'row';

    const col1 = document.createElement('div');
    col1.className = 'col-md-8';

    const selectKlon = ilkSelect.cloneNode(true);
    selectKlon.value = '';
    col1.appendChild(selectKlon);

    const col2 = document.createElement('div');
    col2.className = 'col-md-4';

    const kaldir = document.createElement('button');
    kaldir.type = 'button';
    kaldir.className = 'btn btn-outline-danger btn-sm';
    kaldir.innerHTML = '<i class="fas fa-minus"></i> Kaldir';
    kaldir.addEventListener('click', function() {
        yeniSatir.remove();
    });
    col2.appendChild(kaldir);

    row.appendChild(col1);
    row.appendChild(col2);
    yeniSatir.appendChild(row);

    alan.appendChild(yeniSatir);
}
