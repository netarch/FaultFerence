import numpy as np
import sys
import operator
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
 
pcolors = ['#0e326d', '#000000', '#028413', '#a5669f', '#db850d', '#af0505', '#330066', '#cc6600']
markers = ['o', 's', '^', 'v', 'p', '*', 'p', 'h']
gs_font = fm.FontProperties(fname='gillsans.ttf', size=28, weight='bold')
gs_font_inset = fm.FontProperties(fname='gillsans.ttf', size=15, weight='bold')
gs_font_legend = fm.FontProperties(fname='gillsans.ttf', size=20, weight='bold')
list.reverse(pcolors)
light_grey=(0.5,0.5,0.5)

def string(x):
    if x >= (1024 * 1024 * 1024):
        return str(x/(1024*1024*1024)) + 'B'    
    elif x >= (1024 * 1024):
        return str(x/(1024*1024)) + 'M'
    elif x >= 1024:
        return str(x/1024) + 'K'
    else:
        return str(x)


def plot_lines(xs, ys, yerrs, labels, xlabel, ylabel, outfile):
    pcolors = ["#cf4c32", "#f1a200"]
    # create plot
    fig, ax = plt.subplots()
    ax.set_yscale("log", base=2)
    nlines = len(xs)
    assert (len(ys) == nlines and len(labels) == nlines)
    for i in range(nlines):
        pcolor = pcolors[i]
        print(pcolor)
        markerfacecolor = pcolor
        linestyle = '-'
        if "Micro" in labels[i]:
            linestyle = ':'
        elif "Operator" in labels[i]:
            linestyle = '-.'
            markerfacecolor = 'none'
        #print (pcolor, labels[i], xs[i], ys[i])
        ax.plot(xs[i], ys[i], color=pcolor,  lw=2,  marker=markers[i], mew = 2.5, markersize = 3, markerfacecolor=markerfacecolor, markeredgecolor=pcolor, linestyle=linestyle, dash_capstyle='round', label=labels[i])
        #ax.plot(xs[i], ys[i], '-', color=pcolor,  lw=3.5,  dash_capstyle='round', label=labels[i])
        #ax.scatter(xs[i], ys[i], s=70, color=pcolor, alpha=1.0, marker='x', label=labels[i])
        #ax.errorbar(xs[i], ys[i],  yerr=yerrs[i], color=pcolor,  lw=3.0,  dash_capstyle='round', label=labels[i], fmt='-')
    label_fontsize=25
    ticklabelcolor = 'black'
    # xticks = np.array([0, 6, 12, 18])
    # ax.xaxis.set_ticks(xticks)
    # xticks = np.array([str(x) for x in xticks])
    # ax.set_xticklabels(xticks, color=ticklabelcolor)
    ax.set_xlabel(xlabel, fontsize=label_fontsize)
    ax.set_ylabel(ylabel, fontsize=label_fontsize)
    xlabels = ax.get_xticklabels()
    xlabels[0] = ""
    yticks = np.array([1, 2, 4, 8, 16, 32, 64, 128])
    ax.yaxis.set_ticks(yticks)
    print(xlabels)
    xticks = ax.xaxis.get_major_ticks()
    #xticks[0].label1.set_visible(False)
    #ax.set_xticklabels(xlabels)
    ax.grid(linestyle=':', linewidth=1, color='grey')
    label_fontsize=25
    #if True or not SKEWED:
    #    handles, labels = plt.gca().get_legend_handles_labels()
    #    order = [0,1,2,3,4,5,6]
    #    leg = ax.legend([handles[idx] for idx in order],[labels[idx] for idx in order], bbox_to_anchor=(0.4, 0.65), borderaxespad=0, loc=2, numpoints=2, handlelength=3, prop=gs_font, fontsize=label_fontsize)
    bbox_x, bbox_y = 0.1, 0.59
    # leg = ax.legend(borderaxespad=0, numpoints=1, handlelength=1, prop=gs_font_legend, fontsize=12, bbox_to_anchor=(0.3, 0.3))
    # leg.get_frame().set_linewidth(0.0)
    ax.set_xlabel(xlabel, fontproperties=gs_font, fontsize=label_fontsize)
    ax.set_ylabel(ylabel, fontproperties=gs_font, fontsize=label_fontsize)
    plt.tick_params(labelsize=label_fontsize)
    #lim = ax.get_xlim()
    #ax.set_xticks(list(ax.get_xticks()) + [1.0e-4])
    #ax.set_xlim(lim)
    axcolor='black'
    ax.xaxis.set_tick_params(width=2, length=10)
    ax.yaxis.set_tick_params(width=2, length=15)
    ax.xaxis.set_tick_params(which='both', colors=axcolor)
    ax.yaxis.set_tick_params(which='both', colors=axcolor)
    ax.spines['bottom'].set_color(axcolor)
    ax.spines['top'].set_color(axcolor)
    ax.spines['right'].set_color(axcolor)
    ax.spines['left'].set_color(axcolor)
    ticklabelcolor = 'black'
    ax.tick_params(axis='x', colors=ticklabelcolor, direction="in")
    ax.tick_params(axis='y', colors=ticklabelcolor, direction="in")

    for axis in ['top', 'bottom', 'left', 'right']:
        ax.spines[axis].set_color(light_grey)
    ax.spines['top'].set_linestyle(':')
    ax.spines['right'].set_linestyle(':')

    #plot_lines_inset(xs, ys, fig)
    xc = [0.35, 0.35, 0.45, 0.45, 0.35]
    yc = [0.4, 0.9, 0.9, 0.4, 0.4]
    # ax.plot(xc, yc, color="black",lw=1.5)
    # ax.annotate(" ", xy=(0.72,  0.57), xytext=(0.46, 0.45), arrowprops=dict(arrowstyle="->",lw=2.5),zorder=4)
    for label in ax.get_xticklabels() :
        label.set_fontproperties(gs_font)
        label.set_color(light_grey)
    for label in ax.get_yticklabels() :
        label.set_fontproperties(gs_font)
        label.set_color(light_grey)
    #ax.tick_params(axis='x', labelsize=19, color=light_grey)
    plt.tight_layout()
    # plt.legend(loc="best")
    plt.savefig(outfile)

def string_to_numeric_array(s):
    return [float(x) for x in s.split()]

outfile = sys.argv[1]

eq_size = [122, 121, 120, 119, 118, 117, 116, 115, 114, 113, 112, 111, 110, 102, 101, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 81, 80, 79, 78, 77, 76, 75, 63, 62, 61, 60, 59, 58, 57, 51, 42, 41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 31, 6, 5, 4, 3, 1]
eq_size_2 = [100, 90, 80, 70, 60, 10, 9, 8, 7, 1]
changes = list(range(len(eq_size)))
changes_2 = list(range(len(eq_size_2)))
ys = [eq_size, eq_size_2]
xs = [changes, changes_2]


yerrs = []
ylabel = "Size of equivalent devices"
xlabel = "Number of micro-changes"
plot_lines(xs, ys, yerrs, ["Operator", "FaultFerence"], xlabel, ylabel, outfile)