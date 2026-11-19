/* Vega 6 specs. Interpreted expressions keep charts compatible with the app's CSP. */
(function (root) {
  const font = 'Avenir Next, Segoe UI, sans-serif';
  function speciesSpec(data, width) {
    return {
      $schema: 'https://vega.github.io/schema/vega/v6.json',
      width, height: Math.max(48, data.length * 20), padding: 0,
      autosize: {type:'none', contains:'padding'},
      signals: [{name:'labelWidth', update:'min(134, width * 0.45)'}],
      data: [{name:'species', values:data.map((row, i) => ({...row, rank:i}))}],
      scales: [
        {name:'y', type:'band', domain:{data:'species',field:'species'}, range:'height', padding:.2},
        {name:'x', type:'linear', domain:[0, Math.max(1, ...data.map(row => row.count))], range:[{signal:'labelWidth'}, {signal:'width - 30'}], zero:true}
      ],
      marks: [
        {type:'rect', from:{data:'species'}, encode:{update:{
          x:{signal:'labelWidth'}, x2:{signal:'width - 30'}, y:{scale:'y',field:'species',band:.5,offset:-4},
          height:{value:8}, cornerRadius:{value:3}, fill:{value:'#e9e9ef'}
        }}},
        {type:'rect', from:{data:'species'}, aria:true, encode:{
          update:{x:{signal:'labelWidth'}, x2:{scale:'x',field:'count'}, y:{scale:'y',field:'species',band:.5,offset:-4},
            height:{value:8}, cornerRadius:{value:3},
            fill:{signal:"datum.other ? '#b8b8c5' : datum.rank === 0 ? '#ff633b' : '#555563'"},
            description:{signal:"datum.label + ': ' + datum.count + ' frame sightings'"},
            tooltip:{signal:"{'species': datum.label, 'frames': datum.count}"}},
          hover:{fill:{value:'#ff835f'}}}},
        {type:'text', from:{data:'species'}, encode:{update:{x:{value:0}, y:{scale:'y',field:'species',band:.5},
          baseline:{value:'middle'}, text:{signal:'truncate(datum.label, 21)'}, limit:{signal:'labelWidth - 9'},
          font:{value:font}, fontSize:{value:11}, fill:{signal:"datum.other ? '#9696a3' : '#62626f'"}}}},
        {type:'text', from:{data:'species'}, encode:{update:{x:{signal:'width'}, y:{scale:'y',field:'species',band:.5},
          align:{value:'right'}, baseline:{value:'middle'}, text:{field:'count'}, font:{value:font},
          fontSize:{value:11}, fontWeight:{value:600}, fill:{value:'#484853'}}}}
      ]
    };
  }
  const left = 76, right = 76;
  function activityTopSpec(data, outerWidth) {
    const hours = new Map();
    for (const row of data) hours.set(row.hour, (hours.get(row.hour) || 0) + row.sightings);
    const max = Math.max(1, ...hours.values());
    return {
      $schema:'https://vega.github.io/schema/vega/v6.json', width:Math.max(160, outerWidth-left-right),
      height:28, padding:{left,right,top:2,bottom:22}, autosize:{type:'none',contains:'content'},
      data:[{name:'activity',values:data},{name:'hourTotals',source:'activity',transform:[
        {type:'aggregate',groupby:['hour'],fields:['sightings','checks'],ops:['sum','sum'],as:['sightings','checks']}]}],
      scales:[
        {name:'hour',type:'band',domain:Array.from({length:24},(_,i)=>i),range:'width',paddingInner:.17,paddingOuter:.03},
        {name:'count',type:'linear',domain:[0,max],range:'height',zero:true}
      ],
      axes:[{scale:'hour',orient:'bottom',values:[0,6,12,18,23],domain:false,ticks:false,labelPadding:6,
        labelColor:'#9696a3',labelFont:font,labelFontSize:9,
        encode:{labels:{update:{text:{signal:"format(datum.value, '02') + ':00'"}}}}}],
      marks:[
        {type:'rect',from:{data:'hourTotals'},aria:true,encode:{update:{
          x:{scale:'hour',field:'hour'},width:{scale:'hour',band:1},y:{scale:'count',field:'sightings'},y2:{signal:'height'},
          cornerRadiusTopLeft:{value:2},cornerRadiusTopRight:{value:2},fill:{value:'#9393a5'},
          tooltip:{signal:"{'hour': datum.hour, 'total wildlife frames': datum.sightings, 'analyzed checks': datum.checks}"},
          description:{signal:"datum.hour + ':00: ' + datum.sightings + ' wildlife frames across all buckets'"}},
          hover:{fill:{value:'#ff633b'}}}},
        {type:'text',encode:{update:{x:{value:-left+4},y:{signal:'height-3'},text:{value:'Hourly total'},
          font:{value:font},fontSize:{value:8},fill:{value:'#9999a5'}}}},
        {type:'text',encode:{update:{x:{signal:'width+10'},y:{signal:'height+15'},text:{value:'Total'},
          font:{value:font},fontSize:{value:9},fill:{value:'#9999a5'}}}}
      ]
    };
  }
  function activitySpec(data, dates, outerWidth, labels = dates) {
    const max = data.reduce((n,row)=>Math.max(n,row.sightings),1);
    const totals = new Map();
    for (const row of data) totals.set(row.date,(totals.get(row.date)||0)+row.sightings);
    const maxTotal = Math.max(1, ...totals.values());
    return {
      $schema:'https://vega.github.io/schema/vega/v6.json', width:Math.max(160, outerWidth-left-right),
      height:Math.max(18,dates.length*18), padding:{left,right,top:0,bottom:3},
      autosize:{type:'none', contains:'content'}, data:[
        {name:'activity',values:data},
        {name:'rowTotals',source:'activity',transform:[
          {type:'aggregate',groupby:['date'],fields:['sightings','checks'],ops:['sum','sum'],as:['sightings','checks']}]}
      ],
      scales:[
        {name:'hour',type:'band',domain:Array.from({length:24},(_,i)=>i),range:'width',paddingInner:.17,paddingOuter:.03},
        {name:'date',type:'band',domain:dates,range:'height',paddingInner:.17,paddingOuter:.03},
        {name:'labels',type:'ordinal',domain:dates,range:labels},
        {name:'rowCount',type:'linear',domain:[0,maxTotal],range:[0,40],zero:true},
        {name:'heat',type:'quantize',domain:[0,max],range:['#ffe5db','#ffb69e','#ff8b66','#ff633b','#c54021']}
      ],
      axes:[{scale:'date',orient:'left',domain:false,ticks:false,labelPadding:7,
        labelColor:'#9696a3',labelFont:font,labelFontSize:9,
        encode:{labels:{update:{text:{scale:'labels',field:'value'}}}}}],
      marks:[
        {type:'rect',from:{data:'activity'},aria:true,encode:{
          update:{x:{scale:'hour',field:'hour'},width:{scale:'hour',band:1},y:{scale:'date',field:'date'},height:{scale:'date',band:1},
            cornerRadius:{value:2},strokeWidth:{value:0},
            fill:{signal:"datum.checks === 0 ? '#ececf1' : datum.sightings === 0 ? '#d7d7e1' : scale('heat', datum.sightings)"},
            tooltip:{signal:"{'bucket starting': datum.date, 'hour': datum.hour, 'wildlife frames': datum.sightings, 'analyzed checks': datum.checks}"},
            description:{signal:"datum.date + ', ' + datum.hour + ':00, ' + datum.sightings + ' wildlife frames in ' + datum.checks + ' analyzed checks'"}},
          hover:{stroke:{value:'#73737e'},strokeWidth:{value:1}}}},
        {type:'rect',from:{data:'rowTotals'},aria:true,encode:{update:{x:{signal:'width+10'},
          x2:{signal:"width+10+scale('rowCount', datum.sightings)"},
          y:{scale:'date',field:'date',band:.5,offset:-3},height:{value:6},cornerRadius:{value:2},fill:{value:'#9393a5'},
          tooltip:{signal:"{'bucket starting': datum.date, 'total wildlife frames': datum.sightings, 'analyzed checks': datum.checks}"},
          description:{signal:"datum.date + ': ' + datum.sightings + ' total wildlife frames'"}},hover:{fill:{value:'#ff633b'}}}},
        {type:'text',from:{data:'rowTotals'},encode:{update:{x:{signal:'width+55'},y:{scale:'date',field:'date',band:.5},
          text:{field:'sightings'},baseline:{value:'middle'},font:{value:font},fontSize:{value:9},fill:{value:'#777785'}}}}
      ]
    };
  }
  const charts = {speciesSpec, activitySpec, activityTopSpec};
  if (typeof module !== 'undefined' && module.exports) module.exports = charts;
  else root.AnimalCharts = charts;
})(typeof window === 'undefined' ? globalThis : window);
