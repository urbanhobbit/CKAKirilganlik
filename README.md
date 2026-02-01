# Adana Mahalle Kırılganlık Analizi Paneli 📊

Bu proje, Adana ilindeki mahallelerin çeşitli demografik ve sosyo-ekonomik göstergeler üzerinden kırılganlıklarını analiz etmek için geliştirilmiş bir **Streamlit** uygulamasıdır. Kullanıcılar, etkileşimli haritalar ve grafikler aracılığıyla mahalle bazlı detaylı incelemeler yapabilirler.

## ✨ Temel Özellikler

-   **Katmanlı Harita Görünümü**: PyDeck tabanlı, normalize edilmiş skorlara göre renklenen mahalle bazlı geojson haritası.
-   **Gelişmiş Filtreleme**: İlçe, kentsellik statüsü ve metrik gruplarına (Ana/Alt Endeksler) göre akıllı filtreleme.
-   **Mahalle Karnesi**: Seçilen mahallenin ana ve alt endekslerinin şehir ortalamasıyla karşılaştırıldığı görsel analizler.
-   **İstatistiksel Dağılım**: Seçili metriğin frekans dağılımı ve en yüksek/en düşük puanlı mahallelerin listelenmesi.
-   **Veri Dışa Aktarma**: Filtrelenmiş verilerin CSV formatında indirilmesi.

## 🚀 Kurulum

Projeyi yerel makinenizde çalıştırmak için aşağıdaki adımları izleyin:

1.  **Depoyu Klonlayın**:
    ```bash
    git clone https://github.com/kullanici_adi/repo_adi.git
    cd repo_adi
    ```

2.  **Sanal Ortam Oluşturun (Önerilir)**:
    ```bash
    python -m venv venv
    source venv/bin/activate  # MacOS/Linux
    venv\Scripts\activate     # Windows
    ```

3.  **Bağımlılıkları Yükleyin**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Uygulamayı Çalıştırın**:
    ```bash
    streamlit run app.py
    ```

## 📁 Proje Yapısı

-   `app.py`: Ana uygulama kodu.
-   `data/`: Excel ve GeoJSON veri dosyalarının bulunduğu klasör.
-   `requirements.txt`: Gerekli Python kütüphaneleri.
-   `walkthrough.md`: Özellik tanıtım dökümanı.

## 🛠️ Kullanılan Teknolojiler

-   [Streamlit](https://streamlit.io/): Arayüz ve Sunum
-   [Pandas](https://pandas.pydata.org/): Veri İşleme
-   [GeoPandas](https://geopandas.org/): Coğrafi Veri Analizi
-   [Plotly](https://plotly.com/python/): Etkileşimli Grafikler
-   [PyDeck](https://deckgl.readthedocs.io/): Büyük Ölçekli Harita Görselleştirme

## ⚖️ Lisans

Bu proje [MIT Lisansı](LICENSE) ile lisanslanmıştır.
