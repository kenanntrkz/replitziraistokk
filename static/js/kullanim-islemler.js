/**
 * Kullanim Islemleri
 * Ilac kullanim, gubre kullanim ve ilac grubu CRUD islemleri
 *
 * Fonksiyonlar:
 * - duzenleKullanim(kullanimId)
 * - ilacKullanimKaydet(kullanimId)
 * - duzenleIlacGrubu(tankId)
 * - ilacGrupGuncelle(tankId)
 * - silKullanim(kullanimId)
 * - duzenleGubre(kullanimId)
 * - gubreKullanimKaydet(kullanimId)
 * - silGubre(kullanimId)
 * - silIlacGrubu(tankId)
 */

// ----- ILAC KULLANIM DUZENLEME -----

/**
 * Tekil ilac kullanim kaydini duzenleme formunu acar
 * API'den kayit bilgilerini alir ve modal/form gosterir
 */
function duzenleKullanim(kullanimId) {
    if (!kullanimId) {
        alert('Kullanim ID bulunamadi.');
        return;
    }

    fetch('/api/ilac-kullanim/duzenle/' + kullanimId, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (!data.success) {
            alert('Hata: ' + (data.message || 'Kayit bilgileri alinamadi.'));
            return;
        }

        var kullanim = data.kullanim;

        // Duzenleme modalini olustur veya guncelle
        var modalId = 'duzenleKullanimModal';
        var modal = document.getElementById(modalId);

        if (modal) {
            modal.remove();
        }

        var modalHtml = '<div class="modal fade" id="' + modalId + '" tabindex="-1">' +
            '<div class="modal-dialog">' +
            '<div class="modal-content">' +
            '<div class="modal-header">' +
            '<h5 class="modal-title"><i class="fas fa-edit"></i> Ilac Kullanim Duzenle: ' + kullanim.ilac_adi + '</h5>' +
            '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body">' +
            '<form id="kullanimDuzenleForm" onsubmit="return false;">' +
            '<input type="hidden" id="duzenle_kullanim_id" value="' + kullanim.id + '">' +
            '<div class="mb-3">' +
            '<label class="form-label">Ilac</label>' +
            '<input type="text" class="form-control" value="' + kullanim.ilac_adi + '" disabled>' +
            '</div>' +
            '<div class="mb-3">' +
            '<label class="form-label">Kullanilan Miktar</label>' +
            '<input type="number" step="0.01" class="form-control" id="duzenle_kullanilan_miktar" value="' + kullanim.kullanilan_miktar + '" required>' +
            '</div>' +
            '<div class="mb-3">' +
            '<label class="form-label">Su Miktari (lt)</label>' +
            '<input type="number" step="0.01" class="form-control" id="duzenle_su_miktari" value="' + kullanim.su_miktari + '" required>' +
            '</div>' +
            '<div class="mb-3">' +
            '<label class="form-label">Bag ID</label>' +
            '<input type="number" class="form-control" id="duzenle_bag_id" value="' + (kullanim.bag_id || '') + '">' +
            '</div>' +
            '</form>' +
            '</div>' +
            '<div class="modal-footer">' +
            '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Iptal</button>' +
            '<button type="button" class="btn btn-primary" onclick="ilacKullanimKaydet(' + kullanim.id + ')"><i class="fas fa-save"></i> Kaydet</button>' +
            '</div>' +
            '</div></div></div>';

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        var yeniModal = new bootstrap.Modal(document.getElementById(modalId));
        yeniModal.show();
    })
    .catch(function(err) {
        console.error('Kullanim duzenleme hatasi:', err);
        alert('Kayit bilgileri alinirken bir hata olustu.');
    });
}

/**
 * Tekil ilac kullanim kaydini kaydeder (POST ile gunceller)
 */
function ilacKullanimKaydet(kullanimId) {
    var miktar = document.getElementById('duzenle_kullanilan_miktar');
    var suMiktari = document.getElementById('duzenle_su_miktari');
    var bagId = document.getElementById('duzenle_bag_id');

    if (!miktar || !suMiktari) {
        alert('Form alanlari bulunamadi.');
        return;
    }

    var formData = new FormData();
    formData.append('kullanilan_miktar', miktar.value);
    formData.append('su_miktari', suMiktari.value);
    formData.append('bag_id', bagId ? bagId.value : '');

    fetch('/api/ilac-kullanim/duzenle/' + kullanimId, {
        method: 'POST',
        body: formData
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (data.success) {
            alert(data.message || 'Kayit basariyla guncellendi.');
            // Modali kapat
            var modal = bootstrap.Modal.getInstance(document.getElementById('duzenleKullanimModal'));
            if (modal) modal.hide();
            // Sayfayi yenile
            window.location.reload();
        } else {
            alert('Hata: ' + (data.message || 'Kayit guncellenemedi.'));
        }
    })
    .catch(function(err) {
        console.error('Kullanim kaydet hatasi:', err);
        alert('Kayit sirasinda bir hata olustu.');
    });
}

// ----- ILAC GRUBU DUZENLEME -----

/**
 * Ilac grubunu (tank bazli) duzenleme formunu acar
 * API'den tank bilgilerini ve ilaclari alir
 */
function duzenleIlacGrubu(tankId) {
    if (!tankId) {
        alert('Tank ID bulunamadi.');
        return;
    }

    fetch('/api/ilac-kullanim/duzenle-grup/' + encodeURIComponent(tankId), {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (!data.success) {
            alert('Hata: ' + (data.message || 'Grup bilgileri alinamadi.'));
            return;
        }

        var tank = data.tank;
        var tumIlaclar = data.tum_ilaclar || [];
        var tumBaglar = data.tum_baglar || [];

        // Ilac secimi HTML'i olustur
        var ilacOptionsHtml = '<option value="">-- Ilac Secin --</option>';
        tumIlaclar.forEach(function(ilac) {
            ilacOptionsHtml += '<option value="' + ilac.id + '">' + ilac.ad + ' (Stok: ' + ilac.miktar + ' ' + ilac.birim + ', Dozaj: ' + ilac.dozaj + ')</option>';
        });

        // Bag secimi HTML'i olustur
        var bagOptionsHtml = '<option value="">-- Bag Secin (Opsiyonel) --</option>';
        tumBaglar.forEach(function(bag) {
            var secili = (tank.bag_id && tank.bag_id === bag.id) ? ' selected' : '';
            bagOptionsHtml += '<option value="' + bag.id + '"' + secili + '>' + bag.ad + ' (' + bag.alan + ' donum)</option>';
        });

        // Mevcut ilaclarin listesini olustur
        var mevcutIlaclarHtml = '';
        tank.ilaclar.forEach(function(ilac, index) {
            mevcutIlaclarHtml += '<div class="ilac-grup-satir mb-2" data-index="' + index + '">' +
                '<div class="row align-items-center">' +
                '<div class="col-md-6">' +
                '<select class="form-select grup-ilac-select" name="ilac_id_' + index + '">' +
                ilacOptionsHtml.replace('value="' + ilac.ilac_id + '"', 'value="' + ilac.ilac_id + '" selected') +
                '</select>' +
                '</div>' +
                '<div class="col-md-4">' +
                '<input type="number" step="0.01" class="form-control grup-ilac-miktar" name="miktar_' + index + '" value="' + ilac.kullanilan_miktar + '" placeholder="Miktar">' +
                '</div>' +
                '<div class="col-md-2">' +
                '<button type="button" class="btn btn-sm btn-outline-danger" onclick="this.closest(\'.ilac-grup-satir\').remove()"><i class="fas fa-times"></i></button>' +
                '</div>' +
                '</div></div>';
        });

        // Modal olustur
        var modalId = 'duzenleIlacGrubuModal';
        var modal = document.getElementById(modalId);
        if (modal) modal.remove();

        var modalHtml = '<div class="modal fade" id="' + modalId + '" tabindex="-1">' +
            '<div class="modal-dialog modal-lg">' +
            '<div class="modal-content">' +
            '<div class="modal-header">' +
            '<h5 class="modal-title"><i class="fas fa-edit"></i> Ilac Grubu Duzenle (Tank: ' + tankId + ')</h5>' +
            '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body">' +
            '<div class="mb-3">' +
            '<label class="form-label">Tarih</label>' +
            '<input type="text" class="form-control" id="grup_tarih" value="' + (tank.tarih || '') + '" disabled>' +
            '</div>' +
            '<div class="mb-3">' +
            '<label class="form-label">Bag</label>' +
            '<select class="form-select" id="grup_bag_id">' + bagOptionsHtml + '</select>' +
            '</div>' +
            '<div class="mb-3">' +
            '<label class="form-label">Su Miktari (lt)</label>' +
            '<input type="number" step="0.01" class="form-control" id="grup_su_miktari" value="' + tank.su_miktari + '" required>' +
            '</div>' +
            '<hr>' +
            '<label class="form-label"><strong>Ilaclar</strong></label>' +
            '<div id="grupIlacListesi">' + mevcutIlaclarHtml + '</div>' +
            '<button type="button" class="btn btn-sm btn-outline-success mt-2" onclick="grupIlacSatiriEkle()"><i class="fas fa-plus"></i> Ilac Ekle</button>' +
            '</div>' +
            '<div class="modal-footer">' +
            '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Iptal</button>' +
            '<button type="button" class="btn btn-primary" onclick="ilacGrupGuncelle(\'' + tankId.replace(/'/g, "\\'") + '\')"><i class="fas fa-save"></i> Guncelle</button>' +
            '</div>' +
            '</div></div></div>';

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        // Ilac ekleme icin global option HTML'ini sakla
        window._grupIlacOptionsHtml = ilacOptionsHtml;

        var yeniModal = new bootstrap.Modal(document.getElementById(modalId));
        yeniModal.show();
    })
    .catch(function(err) {
        console.error('Ilac grubu duzenleme hatasi:', err);
        alert('Grup bilgileri alinirken bir hata olustu.');
    });
}

/**
 * Grup duzenleme modaline yeni ilac satiri ekler
 */
function grupIlacSatiriEkle() {
    var liste = document.getElementById('grupIlacListesi');
    if (!liste) return;

    var index = liste.querySelectorAll('.ilac-grup-satir').length;
    var optionsHtml = window._grupIlacOptionsHtml || '<option value="">-- Ilac Secin --</option>';

    var satir = document.createElement('div');
    satir.className = 'ilac-grup-satir mb-2';
    satir.setAttribute('data-index', index);
    satir.innerHTML = '<div class="row align-items-center">' +
        '<div class="col-md-6">' +
        '<select class="form-select grup-ilac-select" name="ilac_id_' + index + '">' + optionsHtml + '</select>' +
        '</div>' +
        '<div class="col-md-4">' +
        '<input type="number" step="0.01" class="form-control grup-ilac-miktar" name="miktar_' + index + '" placeholder="Miktar">' +
        '</div>' +
        '<div class="col-md-2">' +
        '<button type="button" class="btn btn-sm btn-outline-danger" onclick="this.closest(\'.ilac-grup-satir\').remove()"><i class="fas fa-times"></i></button>' +
        '</div>' +
        '</div>';

    liste.appendChild(satir);
}

/**
 * Ilac grubunu (tank bazli) gunceller - tum ilac kayitlarini yeniden olusturur
 */
function ilacGrupGuncelle(tankId) {
    var suMiktari = document.getElementById('grup_su_miktari');
    var bagIdSelect = document.getElementById('grup_bag_id');

    if (!suMiktari || !suMiktari.value) {
        alert('Lutfen su miktarini girin.');
        return;
    }

    // Ilac listesini topla
    var ilaclar = [];
    var satirlar = document.querySelectorAll('#grupIlacListesi .ilac-grup-satir');

    satirlar.forEach(function(satir) {
        var selectEl = satir.querySelector('.grup-ilac-select');
        var miktarEl = satir.querySelector('.grup-ilac-miktar');

        if (selectEl && selectEl.value && miktarEl && miktarEl.value) {
            ilaclar.push({
                ilac_id: parseInt(selectEl.value),
                kullanilan_miktar: parseFloat(miktarEl.value)
            });
        }
    });

    if (ilaclar.length === 0) {
        alert('Lutfen en az bir ilac ekleyin.');
        return;
    }

    var gonderilecekVeri = {
        su_miktari: parseFloat(suMiktari.value),
        bag_id: bagIdSelect ? bagIdSelect.value : null,
        ilaclar: ilaclar
    };

    fetch('/api/ilac-kullanim/duzenle-grup/' + encodeURIComponent(tankId), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(gonderilecekVeri)
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (data.success) {
            alert(data.message || 'Grup basariyla guncellendi.');
            var modal = bootstrap.Modal.getInstance(document.getElementById('duzenleIlacGrubuModal'));
            if (modal) modal.hide();
            window.location.reload();
        } else {
            alert('Hata: ' + (data.message || 'Grup guncellenemedi.'));
        }
    })
    .catch(function(err) {
        console.error('Ilac grup guncelle hatasi:', err);
        alert('Guncelleme sirasinda bir hata olustu.');
    });
}

// ----- ILAC KULLANIM SILME -----

/**
 * Tekil ilac kullanim kaydini siler
 * Silme oncesi kullanicidan onay alir
 */
function silKullanim(kullanimId) {
    if (!kullanimId) {
        alert('Kullanim ID bulunamadi.');
        return;
    }

    if (!confirm('Bu ilac kullanim kaydini silmek istediginize emin misiniz?\nIlac stogu otomatik olarak geri eklenecektir.')) {
        return;
    }

    fetch('/api/ilac-kullanim/sil/' + kullanimId, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (data.success) {
            alert(data.message || 'Kayit basariyla silindi.');
            window.location.reload();
        } else {
            alert('Hata: ' + (data.message || 'Kayit silinemedi.'));
        }
    })
    .catch(function(err) {
        console.error('Kullanim silme hatasi:', err);
        alert('Silme isleminde bir hata olustu.');
    });
}

// ----- ILAC GRUBU SILME -----

/**
 * Belirli bir tank ID'ye sahip tum ilac kullanim kayitlarini siler
 * Tum ilaclar stoklara geri eklenir
 */
function silIlacGrubu(tankId) {
    if (!tankId) {
        alert('Tank ID bulunamadi.');
        return;
    }

    if (!confirm('Bu ilac grubundaki TUM kayitlari silmek istediginize emin misiniz?\nTum ilac stoklari otomatik olarak geri eklenecektir.')) {
        return;
    }

    fetch('/api/ilac-kullanim/sil-grup', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ tank_id: tankId })
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (data.success) {
            alert(data.message || 'Ilac grubu basariyla silindi.');
            window.location.reload();
        } else {
            alert('Hata: ' + (data.message || 'Ilac grubu silinemedi.'));
        }
    })
    .catch(function(err) {
        console.error('Ilac grubu silme hatasi:', err);
        alert('Silme isleminde bir hata olustu.');
    });
}

// ----- GUBRE KULLANIM DUZENLEME -----

/**
 * Gubre kullanim kaydini duzenleme formunu acar
 * API'den kayit bilgilerini alir ve modal gosterir
 */
function duzenleGubre(kullanimId) {
    if (!kullanimId) {
        alert('Kullanim ID bulunamadi.');
        return;
    }

    fetch('/api/gubre-kullanim/duzenle/' + kullanimId, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (!data.success) {
            alert('Hata: ' + (data.message || 'Kayit bilgileri alinamadi.'));
            return;
        }

        var kullanim = data.kullanim;

        var modalId = 'duzenleGubreModal';
        var modal = document.getElementById(modalId);
        if (modal) modal.remove();

        var modalHtml = '<div class="modal fade" id="' + modalId + '" tabindex="-1">' +
            '<div class="modal-dialog">' +
            '<div class="modal-content">' +
            '<div class="modal-header">' +
            '<h5 class="modal-title"><i class="fas fa-edit"></i> Gubre Kullanim Duzenle: ' + kullanim.gubre_adi + '</h5>' +
            '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body">' +
            '<form id="gubreDuzenleForm" onsubmit="return false;">' +
            '<input type="hidden" id="duzenle_gubre_kullanim_id" value="' + kullanim.id + '">' +
            '<div class="mb-3">' +
            '<label class="form-label">Gubre</label>' +
            '<input type="text" class="form-control" value="' + kullanim.gubre_adi + '" disabled>' +
            '</div>' +
            '<div class="mb-3">' +
            '<label class="form-label">Kullanilan Miktar</label>' +
            '<input type="number" step="0.01" class="form-control" id="duzenle_gubre_miktar" value="' + kullanim.kullanilan_miktar + '" required>' +
            '</div>' +
            '<div class="mb-3">' +
            '<label class="form-label">Alan (m2)</label>' +
            '<input type="number" step="0.01" class="form-control" id="duzenle_gubre_alan" value="' + (kullanim.alan || '') + '">' +
            '</div>' +
            '<div class="mb-3">' +
            '<label class="form-label">Bag ID</label>' +
            '<input type="number" class="form-control" id="duzenle_gubre_bag_id" value="' + (kullanim.bag_id || '') + '">' +
            '</div>' +
            '</form>' +
            '</div>' +
            '<div class="modal-footer">' +
            '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Iptal</button>' +
            '<button type="button" class="btn btn-primary" onclick="gubreKullanimKaydet(' + kullanim.id + ')"><i class="fas fa-save"></i> Kaydet</button>' +
            '</div>' +
            '</div></div></div>';

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        var yeniModal = new bootstrap.Modal(document.getElementById(modalId));
        yeniModal.show();
    })
    .catch(function(err) {
        console.error('Gubre duzenleme hatasi:', err);
        alert('Kayit bilgileri alinirken bir hata olustu.');
    });
}

/**
 * Gubre kullanim kaydini kaydeder (POST ile gunceller)
 */
function gubreKullanimKaydet(kullanimId) {
    var miktar = document.getElementById('duzenle_gubre_miktar');
    var alan = document.getElementById('duzenle_gubre_alan');
    var bagId = document.getElementById('duzenle_gubre_bag_id');

    if (!miktar) {
        alert('Form alanlari bulunamadi.');
        return;
    }

    var formData = new FormData();
    formData.append('kullanilan_miktar', miktar.value);
    formData.append('alan', alan ? alan.value : '');
    formData.append('bag_id', bagId ? bagId.value : '');

    fetch('/api/gubre-kullanim/duzenle/' + kullanimId, {
        method: 'POST',
        body: formData
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (data.success) {
            alert(data.message || 'Kayit basariyla guncellendi.');
            var modal = bootstrap.Modal.getInstance(document.getElementById('duzenleGubreModal'));
            if (modal) modal.hide();
            window.location.reload();
        } else {
            alert('Hata: ' + (data.message || 'Kayit guncellenemedi.'));
        }
    })
    .catch(function(err) {
        console.error('Gubre kaydet hatasi:', err);
        alert('Kayit sirasinda bir hata olustu.');
    });
}

// ----- GUBRE KULLANIM SILME -----

/**
 * Gubre kullanim kaydini siler
 * Silme oncesi kullanicidan onay alir
 */
function silGubre(kullanimId) {
    if (!kullanimId) {
        alert('Kullanim ID bulunamadi.');
        return;
    }

    if (!confirm('Bu gubre kullanim kaydini silmek istediginize emin misiniz?\nGubre stogu otomatik olarak geri eklenecektir.')) {
        return;
    }

    fetch('/api/gubre-kullanim/sil/' + kullanimId, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(function(response) {
        return response.json();
    })
    .then(function(data) {
        if (data.success) {
            alert(data.message || 'Kayit basariyla silindi.');
            window.location.reload();
        } else {
            alert('Hata: ' + (data.message || 'Kayit silinemedi.'));
        }
    })
    .catch(function(err) {
        console.error('Gubre silme hatasi:', err);
        alert('Silme isleminde bir hata olustu.');
    });
}
