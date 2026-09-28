# ACB Stats Scraper

## Overview

Esta es una aplicación web basada en Flask que extrae estadísticas de baloncesto del sitio web de la liga española ACB (Asociación de Clubes de Baloncesto) y las convierte en formato XML para descargar. La aplicación permite a los usuarios ingresar una URL de un partido de ACB, extrae las estadísticas de jugadores y equipos de la página web, y genera un archivo XML descargable con los datos estructurados.

## User Preferences

Preferred communication style: Simple, everyday language (Spanish).

## System Architecture

### Frontend Architecture

**Technology**: HTML con CSS embebido
- Aplicación de una sola página con estilos inline
- Diseño con gradiente de fondo (tema púrpura)
- Layout responsivo usando flexbox para centrado
- Interfaz basada en formularios para entrada de URL

**Design Pattern**: Server-side rendering
- Plantillas servidas directamente desde Flask usando Jinja2
- Sin dependencias de frameworks JavaScript
- Flujo de trabajo simple de envío de formularios

### Backend Architecture

**Framework**: Flask (framework web de Python)
- Aproximación de microframework ligero
- Estructura de endpoints RESTful
- Manejo de peticiones basado en rutas

**Core Components**:
1. **Motor de Web Scraping**: Usa BeautifulSoup4 para parseo HTML
   - Extrae nombres de equipos y puntuaciones de tags `<h6>`
   - Parsea estadísticas de jugadores desde tablas HTML
   - Headers User-Agent personalizados para evitar bloqueos
   - Mapeo preciso de columnas de la tabla ACB:
     * cells[0]: Dorsal del jugador
     * cells[1]: Nombre del jugador
     * cells[2]: Minutos jugados
     * cells[3]: Puntos
     * cells[4]: Tiros de 2 puntos
     * cells[6]: Tiros de 3 puntos
     * cells[8]: Tiros libres
     * cells[10]: Rebotes totales
     * cells[12]: Asistencias
     * cells[22]: Valoración

2. **Procesamiento de Datos**: 
   - Convierte datos HTML scrapeados en objetos Python estructurados
   - Equipos y jugadores organizados jerárquicamente
   - Identificación automática de jugadores titulares (asterisco en dorsal o negrita)

3. **Generación XML**: Usa el módulo nativo `xml.etree.ElementTree` de Python
   - Crea documentos XML estructurados desde datos scrapeados
   - Usa `minidom` para formateo pretty-print del XML
   - Genera archivos XML descargables en memoria (usando `io.BytesIO`)
   - Formato específico compatible con sistema de publicación deportiva

**Decisión de Arquitectura**: Modelo stateless request-response
- Sin gestión de sesiones o autenticación de usuario
- Cada petición es independiente
- Sin persistencia de datos entre peticiones

### Data Storage Solutions

**Aproximación**: Sin almacenamiento persistente
- Todo el procesamiento de datos ocurre en memoria durante el ciclo de vida de la petición
- Archivos XML generados on-demand y enviados directamente al cliente
- Sin integración de base de datos

**Razonamiento**: 
- Simplifica el despliegue y reduce requerimientos de infraestructura
- Apropiado para una utilidad de scraping donde no se necesitan datos históricos
- Reduce complejidad y overhead de mantenimiento

### External Dependencies

**Web Scraping**:
- **requests**: Librería HTTP para obtener páginas web de ACB
- **BeautifulSoup4**: Parseo HTML y extracción de datos
- Headers User-Agent personalizados para simular peticiones de navegador

**Procesamiento XML**:
- **xml.etree.ElementTree**: Creación XML nativa de Python
- **xml.dom.minidom**: Formateo y pretty-printing XML

**Framework Web**:
- **Flask**: Framework core de aplicación web
- Renderizado de plantillas integrado (Jinja2)
- Capacidades de servicio de archivos para descargas XML

**Fuente de Datos**: Sitio web oficial de la liga ACB
- Scrapea estadísticas de partidos en vivo desde páginas de juegos públicamente accesibles
- Espera estructura HTML específica (tags h6 para equipos, tablas para estadísticas de jugadores)
- Depende de estructura DOM consistente para parseo

## API Endpoints

### GET /
Renderiza la interfaz web principal con formulario de entrada de URL

### POST /scrape
Extrae datos de la URL de ACB proporcionada y devuelve una vista previa JSON
- **Request body**: `{"url": "https://acb.com/partido/estadisticas/id/XXXXX"}`
- **Response**: JSON con datos de equipos, jugadores e información adicional

### POST /download
Genera y descarga archivo XML con las estadísticas del partido
- **Request body**: `{"url": "https://acb.com/partido/estadisticas/id/XXXXX"}`
- **Response**: Archivo XML descargable (`estadisticas_acb.xml`)

## Estructura del Proyecto

```
.
├── app.py                      # Aplicación Flask principal con scraping y generación XML
├── templates/
│   └── index.html             # Interfaz web con formulario y botones de acción
├── .gitignore                 # Archivos ignorados por git (Python, virtualenv, etc.)
└── replit.md                  # Este archivo
```

## Fecha de Última Actualización

5 de octubre de 2025
