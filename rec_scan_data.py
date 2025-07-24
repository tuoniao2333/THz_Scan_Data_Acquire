# 20250723
import h5py
import numpy as np
import matplotlib.pyplot as plt 
from matplotlib.widgets import Slider

plt.rcParams['font.family'] = 'Arial'

def reconstruct_from_hdf5(file_path):
    with h5py.File(file_path, 'r') as f:
        params = dict(f['scan_parameters'].attrs)
        center_x = params['center_x']
        center_y = params['center_y']
        width = params['width']
        height = params['height']
        step_x = params['step_x']
        step_y = params['step_y']

        positions = np.array(f['positions'])
        max_values = np.array(f['max_values'])
        min_values = np.array(f['min_values'])
        spectra = np.array(f['spectra'])
        time_axis = np.array(f['time_axis'])

    start_x = center_x - width / 2
    end_x = center_x + width / 2
    start_y = center_y - height / 2
    end_y = center_y + height / 2

    x_steps = int(width / step_x) + 1
    y_steps = int(height / step_y) + 1

    peak_image = np.full((y_steps, x_steps), np.nan)
    pp_image = np.full((y_steps, x_steps), np.nan)

    for i,(x,y) in enumerate(positions):
        col = int(round((x-start_x)/step_x))
        row = int(round((y-start_y)/step_y))

        if 0<=row<y_steps and 0<=col<x_steps:
            peak_image[row,col] = max_values[i]
            pp_image[row,col] = max_values[i]-min_values[i]
        
    x_coords = np.linspace(start_x, end_x, x_steps)
    y_coords = np.linspace(start_y, end_y, y_steps)

    return{
        'peak_image':peak_image,
        'pp_image':pp_image,
        'x_coords':x_coords,
        'y_coords':y_coords,
        'spectra':spectra,
        'positions':positions,
        'time_axis':time_axis,
        'params':params
    }

def visualization_peak_img(data):
    plt.figure(figsize=(4,3))
    img = plt.imshow(
        data['peak_image'],
        extent=[data['x_coords'][0], data['x_coords'][-1],
            data['y_coords'][-1], data['y_coords'][0]]
            )
    plt.show()

def visualization_td_signal(data):
    plt.figure(figsize=(4,3))
    plt.plot(data['time_axis'], data['spectra'][0])
    plt.show()

if __name__ == "__main__":
    file_path = "thz_scan_data_acquire\\data\\scan_data_20250716_162657.hdf5"
    scan_data = reconstruct_from_hdf5(file_path)
    visualization_peak_img(scan_data)
    visualization_td_signal(scan_data)