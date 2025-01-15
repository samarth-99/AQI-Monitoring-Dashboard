from pathlib import Path

import ipyleaflet as leaf
import ipywidgets
import pandas as pd
from faicons import icon_svg
from ratelimit import debounce
from shiny import App, Inputs, Outputs, Session, reactive, render, req, ui
from utils import col_numeric, create_map, density_plot, hist_plot, forecast_plot
from location import location_server, location_ui
import openmeteo_requests
import requests_cache
from retry_requests import retry
from shinywidgets import output_widget, reactive_read, render_plotly, render_widget

# Load data
app_dir = Path(__file__).parent
allcities = pd.read_csv(app_dir / "AQI and Lat Long of Countries.csv")

vars = {
    "airquality": "AQI: Air Quality Index",
    "carbmono": "CO: Carbon Monoxide",
    "nitrodio": "NO2: Nitrogen Dioxide",
    "pmfine": "PM2.5: Fine Particulate Matter",
    "ozone": "O3: Ozone"
}

app_ui = ui.page_navbar(
  ui.nav_spacer(),
  ui.nav_panel(
        "Interactive map",
        ui.layout_sidebar(
            ui.sidebar(
                output_widget("density_aqi"),
                output_widget("hist_aqi"),
                position="right",
                width= "400px",
                title=ui.tooltip(
                    ui.span(
                        "Overall density vs in bounds",
                        icon_svg("circle-info").add_class("ms-2"),
                    ),
                    "The density plots show how Air Quality behaves overall (black) in comparison to within view (green)."
                )
            ),
            ui.row(ui.card(
                ui.card_header(
                    "Heatmap showing ",
                    ui.input_select("variable", None, vars, width="auto"),
                    class_="d-flex align-items-center gap-3"
                ),
                output_widget("map"),
                full_screen=True
            )),
            ui.row(ui.output_ui("data_intro"))
            
         )
     ),
  ui.nav_panel(
        "AQI Forecast",
        ui.row(
            ui.column(
            8,
            output_widget("plot")
        ),
        ui.column(
            4,
            ui.panel_well(
                location_ui("location")
            )
        )
        
    ),
    ui.row(
        ui.column(12,
            ui.output_data_frame("hourlyData")
        )
    )
    ),
  fillable = "Interactive map",
  id = "navbar",
#   header = ui.include_css(app_dir / "styles.css"),
  title = ui.popover(
    [
        "AQI Monitor",
        icon_svg("circle-info").add_class("ms-2"),
    ],
    ui.markdown("'AQI Monitor' measures the levels of various pollutants in the air levels in a specific location."),
    placement="right",
),
  window_title = "World AQI Monitor"
)

# ------------------------------------------------------------------------
# Server logic
# ------------------------------------------------------------------------

def server(input: Inputs, output: Outputs, session: Session):
    # ------------------------------------------------------------------------
    # Main map logic
    # ------------------------------------------------------------------------
    loc = location_server("location")
    @render_widget
    def map():
        intial_heatmap = layer_heatmap()
        return create_map(layer= intial_heatmap)

    # Keeps track of whether we're showing markers (zoomed in) or heatmap (zoomed out)
    show_markers = reactive.value(False)

    # Switch from heatmap to markers when zoomed into 200 or fewer cities
    @reactive.effect
    def _():
        cities = cities_in_bounds().shape[0]
        show_markers.set(cities < 250)
        

    # When the variable changes, either update marker colors or redraw the heatmap
    @reactive.effect
    @reactive.event(input.variable)
    def _():
        cities = cities_in_bounds()
        if not show_markers():
            remove_heatmap()
            map.widget.add_layer(layer_heatmap())
        else:
            zip_colors = dict(zip(cities.City, cities_marker_color()))
            for x in map.widget.layers:
                if x.name.startswith("marker-"):
                    zipcode = x.name.split("-")[1]
                    if zipcode in zip_colors:
                        x.color = zip_colors[zipcode]

    # When bounds change, maybe add new markers
    @reactive.effect
    @reactive.event(lambda: cities_in_bounds())
    def _():
        if not show_markers():
            return
        cities = cities_in_bounds()
        if cities.empty:
            return

        current_markers = set(
            [m.name for m in map.widget.layers if m.name.startswith("marker-")]
        )
        cities["Color"] = cities_marker_color()
        for _, row in cities.iterrows():
            if ("marker-" + str(row.City)) not in current_markers:
                map.widget.add_layer(create_marker(row, color=row.Color))

    # Change from heatmap to markers: remove the heatmap and show markers
    # Change from markers to heatmap: hide the markers and add the heatmap
    @reactive.effect
    @reactive.event(show_markers)
    def _():
        if show_markers():
            map.widget.remove_layer(layer_heatmap())
        else:
            map.widget.add_layer(layer_heatmap())

        opacity = 0.6 if show_markers() else 0.0

        for x in map.widget.layers:
            if x.name.startswith("marker-"):
                x.fill_opacity = opacity
                x.opacity = opacity

    @reactive.calc
    def cities_marker_color():
        vals = allcities[input.variable()]
        domain = (vals.min(), vals.max())
        vals_in_bb = cities_in_bounds()[input.variable()]
        return col_numeric(domain)(vals_in_bb)
    
    # when the map is hidden, so only update the bounds when the map is visible
    current_bounds = reactive.value()

    @reactive.effect
    def _():
        bb = reactive_read(map.widget, "bounds")
        if input.navbar() != "Interactive map":
            return
        with reactive.isolate():
            current_bounds.set(bb)

    @debounce(0.3)
    @reactive.calc
    def cities_in_bounds():
        bb = req(current_bounds())

        lats = (bb[0][0], bb[1][0])
        lons = (bb[0][1], bb[1][1])
        return allcities[
            (allcities.Lat >= lats[0])
            & (allcities.Lat <= lats[1])
            & (allcities.Long >= lons[0])
            & (allcities.Long <= lons[1])
        ]

    @reactive.calc
    def layer_heatmap():
        locs = allcities[["Lat", "Long", input.variable()]].to_numpy()
        return leaf.Heatmap(
            locations=locs.tolist(),
            radius = 25, blur = 15
        )

    def remove_heatmap():
        for x in map.widget.layers:
            if x.name == "heatmap":
                map.widget.remove_layer(x)

    zip_selected = reactive.value(None)

    # Utility function to create a marker
    def create_marker(row, **kwargs):
        m = leaf.CircleMarker(
            location=(row.Lat, row.Long),
            popup=ipywidgets.HTML(
                f"""
            {row.City}, {row.Country} <br/>
            {row.airquality:.0f} Air Quality<br/>
            {row.carbmono:.1f} Carbon Monoxide<br/>
            {row.nitrodio:.0f} Nitrogen Dioxide<br/>
            {row.ozone} Ozone<br/>
            """
            ),
            name=f"marker-{row.City}",
            **kwargs,
        )

        def _on_click(**kwargs):
            coords = kwargs["coordinates"]
            idx = (allcities.Lat == coords[0]) & (allcities.Long == coords[1])
            zip_selected.set(allcities[idx])

        m.on_click(_on_click)

        return m
    
    @render_plotly
    def density_aqi():
        return density_plot(
            allcities,
            cities_in_bounds(),
            selected=zip_selected(),
            var="airquality",
            title="AQI"
        )

    @render_plotly
    def hist_aqi():
        return hist_plot(
            allcities,
            cities_in_bounds(),
            selected=zip_selected(),
            var="airquality",
            title="AQI",
            showlegend=True,
        )

    @render.ui
    def data_intro():
        cities = cities_in_bounds()

        md = ui.markdown(
            f"""
            {cities.shape[0]} stations are currently within the map's viewport, and amongst them:

              * AQI Mean is {cities.airquality.mean():.1f}
              * Mean Carbon Monoxide is {cities.carbmono.mean():.1f}
              * Mean Nitrogen Dioxide is {cities.nitrodio.mean():.1f}
              * Mean PM 2.5 is {cities.pmfine.mean():.1f}
              * Mean Ozone is {cities.ozone.mean():.1f}
                """
        )

        return ui.div(md, class_="my-3 lead")

    @render.data_frame
    def hourlyData():
        return render.DataGrid(getForecast(), width = "100%")

    @reactive.calc()
    def getForecast():
        # Setup the Open-Meteo API client with cache and retry on error
        cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
        retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
        openmeteo = openmeteo_requests.Client(session = retry_session)
        lat, long = loc()
        # Make sure all required weather variables are listed here
        # The order of variables in hourly or daily is important to assign them correctly below
        url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        params = {
            "latitude": lat,
            "longitude": long,
            "current": ["european_aqi", "pm10", "pm2_5", "carbon_monoxide", "nitrogen_dioxide", "ozone"],
            "hourly": ["european_aqi","pm10", "pm2_5", "carbon_monoxide", "nitrogen_dioxide", "ozone"]
        }
        responses = openmeteo.weather_api(url, params=params)

        # Process first location. Add a for-loop for multiple locations or weather models
        response = responses[0]
        # Current values. The order of variables needs to be the same as requested.
        current = response.Current()
        current_european_aqi = current.Variables(0).Value()
        current_pm10 = current.Variables(1).Value()
        current_pm2_5 = current.Variables(2).Value()
        current_carbon_monoxide = current.Variables(3).Value()
        current_nitrogen_dioxide = current.Variables(4).Value()
        current_ozone = current.Variables(5).Value()

        hourly = response.Hourly()
        hourly_pm10 = hourly.Variables(0).ValuesAsNumpy()
        hourly_pm2_5 = hourly.Variables(1).ValuesAsNumpy()
        hourly_carbon_monoxide = hourly.Variables(2).ValuesAsNumpy()
        hourly_nitrogen_dioxide = hourly.Variables(3).ValuesAsNumpy()
        hourly_ozone = hourly.Variables(4).ValuesAsNumpy()
        hourly_european_aqi = hourly.Variables(5).ValuesAsNumpy()

        hourly_data = {"date": pd.date_range(
            start = pd.to_datetime(hourly.Time(), unit = "s"),
            end = pd.to_datetime(hourly.TimeEnd(), unit = "s"),
            freq = pd.Timedelta(seconds= hourly.Interval()),
            inclusive = "left"
        )}

        hourly_data["european_aqi"] = hourly_european_aqi
        hourly_data["pm2_5"] = hourly_pm2_5
        hourly_data["pm10"] = hourly_pm10
        hourly_data["carbon_monoxide"] = hourly_carbon_monoxide
        hourly_data["nitrogen_dioxide"] = hourly_nitrogen_dioxide
        hourly_data["ozone"] = hourly_ozone

        hourly_dataframe = pd.DataFrame(data = hourly_data)
        return hourly_dataframe

    @render_widget
    def plot():
        return forecast_plot(getForecast())


app = App(app_ui, server, static_assets=app_dir / "www")
