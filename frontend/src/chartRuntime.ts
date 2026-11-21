import {init,use} from 'echarts/core';
import {LineChart,BarChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,LegendComponent,DataZoomComponent} from 'echarts/components';
import {CanvasRenderer} from 'echarts/renderers';
use([LineChart,BarChart,GridComponent,TooltipComponent,LegendComponent,DataZoomComponent,CanvasRenderer]);
export {init};
