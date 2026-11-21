import gzip
import os
import xml.etree.ElementTree as ET
import pandas as pd


def find_events_file(base_dir):
    """Busca el archivo de eventos en las ubicaciones estándar de MATSim."""
    candidates = [
        os.path.join(base_dir, "output_events.xml.gz"),
        os.path.join(base_dir, "output_events.xml"),
        os.path.join(base_dir, "ITERS", "it.0", "0.events.xml.gz"),
        os.path.join(base_dir, "ITERS", "it.0", "0.events.xml"),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        f"No se encontró ningún archivo de eventos en: {base_dir}"
    )


def parse_matsim_events(events_path):
    # Detectar si el archivo está comprimido en .gz
    if events_path.endswith(".gz"):
        file_obj = gzip.open(events_path, "rb")
    else:
        file_obj = open(events_path, "rb")

    events_data = []

    try:
        # Iterar sobre las etiquetas <event> del XML
        context = ET.iterparse(file_obj, events=["start", "end"])
        for event, elem in context:
            if event == "end" and elem.tag == "event":
                events_data.append(elem.attrib)
                elem.clear()  # Liberar memoria RAM durante el parseo
    finally:
        file_obj.close()

    return pd.DataFrame(events_data)


if __name__ == "__main__":
    output_directory = "output/labs/01-linea-recta"

    try:
        events_file = find_events_file(output_directory)
        print(f"Leyendo archivo de eventos desde: {events_file}")

        df_events = parse_matsim_events(events_file)

        # Filtrar eventos relevantes para el análisis del viaje
        travel_events = df_events[
            df_events["type"].isin(
                ["left link", "entered link", "actstart", "actend"]
            )
        ]

        print("\n=== Resumen de Eventos de Movilidad ===")
        print(
            travel_events[
                ["time", "type", "person", "link", "actType"]
            ].dropna(how="all")
        )

    except Exception as e:
        print(f"Error procesando eventos: {e}")