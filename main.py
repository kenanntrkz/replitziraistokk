import os
import logging
from app import app
from routes import *

# Ensure initial data is created
if __name__ == "__main__":
    # Loglama yapılandırması
    os.makedirs('logs', exist_ok=True)
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),  # Konsola log
            logging.FileHandler('logs/app.log')  # Dosyaya log
        ]
    )
    
    # Flask uygulaması için logger
    app.logger.setLevel(logging.DEBUG)
    app.logger.info("Uygulama başlatılıyor...")
    
    # Initialize the pesticides file
    from routes import check_pesticides_file
    check_pesticides_file()
    
    # Run the Flask app on port 5000 for deployment
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
