from typing import List, Optional, Tuple

import ipyleaflet as leaf
import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
import plotly.figure_factory as ff
import plotly.graph_objs as go
from ipyleaflet import basemaps

def create_map(**kwargs):
    map = leaf.Map(
        center=(0, 0),
        zoom=2,
        scroll_wheel_zoom=True,
        attribution_control=False,
        **kwargs,
    )
    map.add_layer(leaf.basemap_to_tiles(basemaps.CartoDB.DarkMatter))
    if "layer" in kwargs:
        map.add_layer({kwargs['layer']})
    search = leaf.SearchControl(
        url="https://nominatim.openstreetmap.org/search?format=json&q={s}",
        position="topleft",
        zoom=9,
    )
    map.add(search)
    return map

def density_plot(
    overall: pd.DataFrame,
    in_bounds: pd.DataFrame,
    var: str,
    selected: Optional[pd.DataFrame] = None,
    title: Optional[str] = None,
    showlegend: bool = False,
):
  
    if in_bounds.empty:
        return None

    dat = [overall[var], in_bounds[var]]
    fig = ff.create_distplot(dat, ["Overall AQI", "In Bounds AQI"], colors=["black", "#6DCD59"], show_rug=False, show_hist=False)

    # Calculate min & max values for auto-zoom
    min_x, max_x = min(overall[var].min(), in_bounds[var].min()), max(overall[var].max(), in_bounds[var].max())
    buffer = 10  # Adjust zoom buffer

    # Update layout with dynamic zoom
    fig.update_layout(
        xaxis=dict(title="AQI Level", range=[min_x - buffer, max_x + buffer], showline=True),
        yaxis=dict(title="Density", showgrid=True, showline=True, showticklabels=True, zeroline=False),
        height=300, template="plotly_white"
    )

    if selected is not None:
        x = selected[var].tolist()[0]
        fig.add_shape(
            type="line",
            x0=x,
            x1=x,
            y0=0,
            y1=1,
            yref="paper",
            line=dict(width=1, dash="dashdot", color="gray"),
        )

    return go.FigureWidget(data=fig.data, layout=fig.layout)

def hist_plot(
    overall: pd.DataFrame,
    in_bounds: pd.DataFrame,
    var: str,
    selected: Optional[pd.DataFrame] = None,
    title: Optional[str] = None,
    showlegend: bool = False,
):
    if in_bounds.empty:
        return None

    # Create histogram traces
    fig = go.Figure()

    fig.add_trace(go.Histogram(
        x=overall[var],
        name="Overall AQI",
        opacity=0.6,
        marker=dict(color="black"),
        nbinsx=30  # Adjust bin count
    ))

    fig.add_trace(go.Histogram(
        x=in_bounds[var],
        name="In Bounds AQI",
        opacity=0.6,
        marker=dict(color="#6DCD59"),
        nbinsx=30  # Adjust bin count
    ))

    # Update layout to show number instead of density
    fig.update_layout(
        barmode="overlay",  # Overlay histograms
        height=300,
        showlegend=True,
        margin=dict(l=40, r=0, t=30, b=40),
        legend=dict(x=0.5, y=1, orientation="h", xanchor="center", yanchor="bottom"),
        xaxis=dict(title="AQI Level", showline=True, zeroline=False),
        yaxis=dict(
            title="Number of Observations",
            showgrid=True,
            showline=True,
            showticklabels=True,
            zeroline=False,
        ),
        template="plotly_white"
    )

    return go.FigureWidget(data=fig.data, layout=fig.layout)

def forecast_plot(
        forecast_df:pd.DataFrame
    ):
    forecast_df["date"] = pd.to_datetime(forecast_df["date"])

    fig = go.Figure()

    # Define pollutants for primary y-axis
    primary_pollutants = ["pm10", "pm2_5", "ozone", "carbon_monoxide"]

    for pollutant in primary_pollutants:
        fig.add_trace(go.Scatter(
            x=forecast_df["date"], 
            y=forecast_df[pollutant],
            mode="lines+markers",
            name=pollutant.upper(),
            yaxis="y1"  
        ))

    # Add trace for European AQI on secondary y-axis
    fig.add_trace(go.Scatter(
        x=forecast_df["date"], 
        y=forecast_df["european_aqi"],
        mode="lines+markers",
        name="European AQI",
        line=dict(dash="dash"),
        yaxis="y2"  # Assign to secondary y-axis
    ))

    fig.update_layout(
        title="Air Quality Hourly Forecast",
        xaxis=dict(
            title="Date and Time"
            # tickformat="%Y-%m-%d %H:%M",
            # type="date"
        ),
        yaxis=dict(
            title="Concentration (µg/m³ & ppm)",
            side="left",
            showgrid=True
        ),
        yaxis2=dict(
            title="European AQI",
            overlaying="y",
            side="right",
            showgrid=False
        ),
        hovermode="x unified"
    )

    return fig

color_palette = plt.get_cmap("RdYlGn_r", 6)

# TODO: how to handle nas (pd.isna)?
def col_numeric(domain: Tuple[float, float], na_color: str = "#808080"):
    rescale = mpl.colors.Normalize(0, domain[1])

    def _(vals: List[float]) -> List[str]:
        cols = color_palette(rescale(vals))
        return [mpl.colors.to_hex(v) for v in cols]

    return _
