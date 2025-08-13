# Sewerage Depth Estimator

A QGIS plugin for optimizing sewerage system design through real-time depth estimation and automated network calculations.

## Overview

This plugin assists engineers in designing sewerage systems by automatically calculating segment depths and managing network updates during the design process. Developed to complement **[SaniHUB RedBasica](https://github.com/EL-BID/red_basica)**.

## Key Features

- **Real-time depth estimation** during design
- **Automatic downstream network recalculation** when upstream segments are added
- **Smart editing response** - recalculates affected segments when modifications are made
- **Optimized design workflows** reducing manual calculation time

## Installation

1. Download or clone this repository
2. Copy the plugin folder to your QGIS plugins directory
3. Enable the plugin in QGIS Plugin Manager (Sewerage Depth Estimator)

## Quick Start

1. Load your sewerage network layer (line features)
2. Load a DEM layer for elevation data
3. Configure design parameters (cover depth, diameter, slope)
4. Start designing - depths are calculated automatically

## Requirements

- QGIS 3.x

## Companion Plugin

Works seamlessly with **[SaniHUB RedBasica](https://github.com/EL-BID/red_basica)** for comprehensive sewerage network design.

## License

This project is licensed under the GNU General Public License v2.0 - see the LICENSE file for details.

